package tm.yol.vpn

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.VpnService
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.ParcelFileDescriptor
import libv2ray.CoreCallbackHandler
import libv2ray.CoreController
import libv2ray.Libv2ray
import java.util.concurrent.ConcurrentHashMap

/** Ekran ile servis arasında durum paylaşımı (aynı süreç). */
object State {
    const val OFF = 0; const val WAIT = 1; const val ON = 2; const val FAIL = 3
    @Volatile var now = OFF
    private val main = Handler(Looper.getMainLooper())
    val subs = mutableListOf<() -> Unit>()
    @Volatile var app: Context? = null
    fun set(s: Int) {
        now = s
        main.post { subs.toList().forEach { it() } }
        app?.let { Tile.refresh(it) }
    }

    @Volatile var active: Server? = null          // şu an bağlı olunan sunucu (otomatikte seçilen)
    @Volatile var core: CoreController? = null    // bağlıyken: tünel içinden ping ölçmek için
    @Volatile var ms = 0L                         // bağlı sunucunun ms'i (0 = henüz ölçülmedi, -1 = yanıt yok)
    @Volatile var socks = 0                       // bağlıyken: programmanyň öz habarlary üçin yerli SOCKS porty
    @Volatile var onAt = 0L                       // soňky birikme wagty (ms)

    /** Varsayılan otomatik. Elle seçilen sunucu listeden kalkarsa yine otomatiğe döner. */
    fun selected(ctx: Context): Server? {
        val k = ctx.getSharedPreferences("p", 0).getString("sel", AUTO)
        return if (k == AUTO) null else Sub.list.firstOrNull { it.key == k }
    }
    fun select(ctx: Context, s: Server?) =
        ctx.getSharedPreferences("p", 0).edit().putString("sel", s?.key ?: AUTO).apply()
    private const val AUTO = "auto"

    // ---- ping önbelleği: açılışta ve «Barla»da ölçülür, bağlanırken bekletmez ----
    val pings = ConcurrentHashMap<String, Long>()   // server.key → ms (-1 = yok)
    @Volatile var pingAt = 0L
    private fun cands() = Sub.list.filter { !it.ru && !it.game }.ifEmpty { Sub.list.filter { !it.ru } }

    fun ping(s: Server): Long = runCatching { Libv2ray.measureOutboundDelay(Cfg.full(s.uri, false), PING) }
        .getOrDefault(-1L).let { if (it > 0) it else -1L }.also { pings[s.key] = it }

    /** Arka planda bütün adayları ölçer (açılışta). */
    fun warm() {
        val c = cands(); if (c.isEmpty()) return
        val pool = java.util.concurrent.Executors.newFixedThreadPool(minOf(c.size, 8))
        c.forEach { s -> pool.execute { ping(s) } }
        pool.shutdown(); pool.awaitTermination(15, java.util.concurrent.TimeUnit.SECONDS)
        pingAt = System.currentTimeMillis()
    }

    @Volatile var noPing = false   // son otomatik denemede hiçbir kod yanıt vermedi
    @Volatile var noNet = false    // telefonun interneti yok / çalışmıyor

    /** İnternet var mı: ağ bağlı mı ve Google'a (Türkmenistan'da açık olan googleapis.com) ulaşılıyor mu. */
    fun online(ctx: Context): Boolean {
        val cm = ctx.getSystemService(android.net.ConnectivityManager::class.java)
        val caps = runCatching { cm.getNetworkCapabilities(cm.activeNetwork) }.getOrNull() ?: return false
        if (!caps.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_INTERNET)) return false
        return runCatching {
            val c = java.net.URL("https://www.googleapis.com/generate_204").openConnection() as java.net.HttpURLConnection
            c.connectTimeout = 5000; c.readTimeout = 5000
            try { c.responseCode > 0 } finally { c.disconnect() }
        }.getOrDefault(false)
    }

    /**
     * Otomatik: her bağlanmada Rusya ve oyun dışındaki bütün kodlara gerçekten ping atılır,
     * yanıt verenlerden biri seçilir (ilk yanıttan sonra kısa süre beklenir, iyi olanlar arasından rastgele).
     * Hiçbiri yanıt vermezse null: ms vermeyen koda asla bağlanılmaz.
     */
    fun best(ctx: Context): Server? {
        noPing = false; noNet = false
        if (!online(ctx)) { noNet = true; return null }
        val c = cands()
        if (c.isEmpty()) return null
        val got = ConcurrentHashMap<Server, Long>()
        val pool = java.util.concurrent.Executors.newFixedThreadPool(minOf(c.size, 8))
        c.forEach { s -> pool.execute { ping(s).takeIf { it > 0 }?.let { got[s] = it } } }
        pool.shutdown()
        val end = System.currentTimeMillis() + 9000
        var first = 0L
        while (System.currentTimeMillis() < end && !pool.isTerminated) {
            if (got.isNotEmpty() && first == 0L) first = System.currentTimeMillis()
            if (first > 0 && System.currentTimeMillis() - first > 1200) break   // ilk yanıttan sonra 1.2 sn daha
            Thread.sleep(80)
        }
        pool.shutdownNow()
        pingAt = System.currentTimeMillis()
        if (got.isEmpty()) { if (online(ctx)) noPing = true else noNet = true; return null }
        val min = got.values.min()
        val good = got.filter { it.value <= min * 2 + 150 }.keys.toList()   // en iyiye yakın olanlar
        val last = active?.key
        return (good.filter { it.key != last }.ifEmpty { good }).random().also { ms = got[it] ?: 0L }     // her seferinde aynısına takılmasın
    }
    const val PING = "https://www.gstatic.com/generate_204"
}

class Svc : VpnService() {
    private var tun: ParcelFileDescriptor? = null
    private var core: CoreController? = null
    private val lock = Any()
    @Volatile private var want = false
    @Volatile private var gen = 0                 // her bağlan/kapat isteğinde artar: eski deneme sonucu yok sayılır
    private val h = Handler(Looper.getMainLooper())
    private var beatAt = 0L
    private val tick = object : Runnable {
        override fun run() {
            // 1 sagat dolunca (key yoksa) VPN durur; kullanıcı elle yeniden başlatır
            if (want && State.now == State.ON && Lic.left(this@Svc) == 0L) { stop(); expired(); return }
            if (want && State.now == State.ON && System.currentTimeMillis() - beatAt > 5 * 60_000) {
                beatAt = System.currentTimeMillis(); Thread { Stats.beat(this@Svc, true) }.start()
            }
            if (want) h.postDelayed(this, 10_000)
        }
    }

    override fun onCreate() { super.onCreate(); State.app = applicationContext; Lang.init(this) }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == STOP) { stop(); return START_NOT_STICKY }
        foreground()
        if (Upd.busy(this)) { stopForeground(STOP_FOREGROUND_REMOVE); stopSelf(); return START_NOT_STICKY }   // güncelleme bitene kadar VPN açılmaz
        val reconnect = State.now == State.ON && Lic.start(this) > 0   // sunucu değiştirmek süreyi sıfırlamaz
        if (!reconnect) Lic.setStart(this, 0)
        want = true
        State.set(State.WAIT)
        h.removeCallbacks(tick); h.post(tick)
        val g = ++gen
        Thread { start(g) }.start()
        return START_NOT_STICKY
    }

    private fun start(g: Int) = synchronized(lock) {
        if (!want || g != gen) return
        try {
            stopCore()
            // 1.16: her birikmede ilki abuna täzelenýär (iň köp 5 sn). Gijä galsa — häzirki sanawdan iň çalt jogap bereni saýlanýar
            val app = applicationContext
            val th = Thread { runCatching { if (Sub.refresh(app, 5000)) Msg.events.add(org.json.JSONObject().put("k", "srv")) } }.apply { isDaemon = true; start() }
            th.join(5000)
            val slow = th.isAlive
            if (Sub.list.isEmpty()) Sub.load(this)
            if (!want || g != gen) return
            State.noPing = false; State.noNet = false; State.ms = 0
            val sel = if (slow) null else State.selected(this)
            if (sel != null && !State.online(this)) { State.noNet = true; throw IllegalStateException("internet yok") }
            val s = sel ?: State.best(this) ?: throw IllegalStateException("ping yok")
            if (sel != null) State.ms = State.pings[sel.key]?.takeIf { it > 0 && System.currentTimeMillis() - State.pingAt < 5 * 60_000 } ?: 0L
            State.active = s
            val port = 20000 + java.security.SecureRandom().nextInt(20000)
            val cfg = Cfg.full(s.uri, true, port)
            Libv2ray.initCoreEnv(filesDir.absolutePath, "")
            val b = Builder().setSession(getString(R.string.app_name)).setMtu(1500)
                .addAddress("172.19.0.1", 30).addRoute("0.0.0.0", 0)
                .addAddress("fdfe:dcba:9876::1", 126).addRoute("::", 0)
                .addDnsServer("1.1.1.1")
            b.addDisallowedApplication(packageName)   // Xray'in kendi bağlantıları tünele girmesin
            if (Build.VERSION.SDK_INT >= 29) b.setMetered(false)
            val fd = b.establish() ?: throw IllegalStateException("izin yok")
            tun = fd
            val c = Libv2ray.newCoreController(object : CoreCallbackHandler {
                override fun startup(): Long = 0
                override fun shutdown(): Long = 0
                override fun onEmitStatus(p0: Long, p1: String?): Long = 0
            })
            core = c
            c.startLoop(cfg, fd.fd)
            State.core = c
            State.socks = port
            if (!want || g != gen) { stopCore(); return }
            if (Lic.start(this) == 0L) Lic.setStart(this, System.currentTimeMillis())   // 1 sagat bağlanınca başlar
            State.onAt = System.currentTimeMillis()
            State.set(State.ON)
            Msg.start(applicationContext); Msg.kick()
            runCatching { getSystemService(NotificationManager::class.java).notify(1, note(s)) }   // bildirim: «Birikdirildi · ülke»
            if (slow) Thread { if (System.currentTimeMillis() - Sub.okAt > 60_000) Sub.refresh(app) }.start()
        } catch (e: Throwable) {
            stopCore()
            if (!want || g != gen) return   // kullanıcı iptal etti ya da yeni bağlantı istendi
            State.set(State.FAIL)
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private fun stopCore() {
        State.core = null; State.socks = 0
        runCatching { core?.stopLoop() }
        core = null
        runCatching { tun?.close() }
        tun = null
    }

    private fun stop() {
        want = false; gen++
        h.removeCallbacks(tick)
        Lic.setStart(this, 0)
        State.set(State.OFF)
        val app = applicationContext
        Thread {
            synchronized(lock) { stopCore() }
            Sub.refresh(app)                     // her çıkışta sessiz güncelleme
        }.start()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onRevoke() { stop() }
    override fun onDestroy() { want = false; h.removeCallbacks(tick); Thread { synchronized(lock) { stopCore() } }.start(); if (State.now != State.FAIL) State.set(State.OFF); super.onDestroy() }

    private fun foreground() {
        val nm = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26)
            nm.createNotificationChannel(NotificationChannel("v", "VPN", NotificationManager.IMPORTANCE_LOW))
        val n = note(null)
        if (Build.VERSION.SDK_INT >= 34) startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        else startForeground(1, n)
    }

    /** s == null: bağlanıyor; değilse «Birikdirildi · ülke». */
    private fun note(s: Server?): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, Main::class.java), PendingIntent.FLAG_IMMUTABLE)
        val off = PendingIntent.getService(this, 1, Intent(this, Svc::class.java).setAction(STOP), PendingIntent.FLAG_IMMUTABLE)
        val nb = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, "v") else Notification.Builder(this)
        val txt = if (s == null) t("Birikdirilýär…", "Подключение…", "Bağlanıyor…")
            else t("Birikdirildi", "Подключено", "Bağlandı") + " · " + s.flag + " " + s.country
        return nb.setSmallIcon(R.drawable.ic_notif).setContentTitle(getString(R.string.app_name))
            .setContentText(txt).setContentIntent(open).setOngoing(true)
            .addAction(Notification.Action.Builder(null, t("Öçür", "Отключить", "Kapat"), off).build()).build()
    }

    /** 1 sagat dolunca: VPN neden kapandı, kullanıcı bilsin. */
    private fun expired() = runCatching {
        val nm = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(NotificationChannel("e", "VPN", NotificationManager.IMPORTANCE_DEFAULT))
        val open = PendingIntent.getActivity(this, 4, Intent(this, Main::class.java), PendingIntent.FLAG_IMMUTABLE)
        val nb = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, "e") else Notification.Builder(this)
        val txt = t("1 sagat doldy, VPN öçdi. Dowam etmek üçin täzeden birikiň ýa-da açar alyň.", "1 час истёк, VPN отключён. Подключитесь снова или купите ключ.",
            "1 saat doldu, VPN kapandı. Yeniden bağlanın ya da anahtar alın.")
        nm.notify(3, nb.setSmallIcon(R.drawable.ic_notif).setContentTitle(getString(R.string.app_name)).setContentText(txt)
            .setStyle(Notification.BigTextStyle().bigText(txt)).setContentIntent(open).setAutoCancel(true).build())
    }

    companion object {
        const val STOP = "stop"

        /** Programma ýapykka admin jogap berse: bildiriş. */
        fun notifyReply(ctx: Context, text: String) = runCatching {
            val nm = ctx.getSystemService(NotificationManager::class.java)
            if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(NotificationChannel("m", t("Admin jogaby", "Ответ админа", "Yönetici yanıtı"), NotificationManager.IMPORTANCE_DEFAULT))
            val open = PendingIntent.getActivity(ctx, 5, Intent(ctx, Main::class.java).setAction(Main.CHAT), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val nb = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(ctx, "m") else Notification.Builder(ctx)
            val title = "💬 " + t("Admin jogap berdi", "Ответ админа", "Yönetici yanıtladı")
            nm.notify(6, nb.setSmallIcon(R.drawable.ic_notif).setContentTitle(title).setContentText(text.take(200))
                .setStyle(Notification.BigTextStyle().bigText(text.take(500))).setContentIntent(open).setAutoCancel(true).build())
        }
    }
}
