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
    @Volatile var hold = false                    // 1.28: kill switch — VPN kesildi, internet ýapyk saklanýar

    /** Varsayılan otomatik. Elle seçilen sunucu listeden kalkarsa yine otomatiğe döner. */
    fun selected(ctx: Context): Server? {
        val k = ctx.getSharedPreferences("p", 0).getString("sel", AUTO)
        return if (k == null || k.startsWith(AUTO)) null else Sub.list.firstOrNull { it.key == k }?.takeIf { allowed(ctx, it) }   // 1.43: Premium gutarsa — awtomatik (mugt)
    }
    fun select(ctx: Context, s: Server?, prem: Boolean = false) =
        ctx.getSharedPreferences("p", 0).edit().putString("sel", s?.key ?: if (prem) AUTO_P else AUTO).apply()
    fun selKey(ctx: Context): String = ctx.getSharedPreferences("p", 0).getString("sel", AUTO) ?: AUTO
    /** 1.46.4: awtomatik — Premium bölüminden saýlanan bolsa diňe Premium serwerler, Free-den bolsa diňe mugtlar. */
    private fun autoPrem(ctx: Context) = selKey(ctx) == AUTO_P && Lic.prem(ctx)
    /** 1.47: baş sahypadaky PUBG düwmesi — awtomatik diňe PUBG serwerlerinden saýlaýar. */
    fun pubg(ctx: Context) = ctx.getSharedPreferences("p", 0).getBoolean("pubg", false)
    fun setPubg(ctx: Context, on: Boolean) = ctx.getSharedPreferences("p", 0).edit().putBoolean("pubg", on).apply()
    /** 1.47: awtomatik birikme — PUBG / Premium-da işleýän kod ýok bolsa düwme özi öçýär we adaty (mugt) koda birikýär, programma sebäbini aýdýar. */
    fun bestFb(ctx: Context): Server? {
        best(ctx)?.let { return it }
        if (noNet) return null
        if (pubg(ctx)) { setPubg(ctx, false); Msg.events.add(org.json.JSONObject().put("k", "fb").put("w", "pubg")); best(ctx)?.let { return it } }
        if (autoPrem(ctx)) { select(ctx, null, false); Msg.events.add(org.json.JSONObject().put("k", "fb").put("w", "prem")); best(ctx)?.let { return it } }
        return null
    }
    private const val AUTO_P = "auto:p"
    private const val AUTO = "auto"

    // ---- ping önbelleği: açılışta ve «Barla»da ölçülür, bağlanırken bekletmez ----
    val pings = ConcurrentHashMap<String, Long>()   // server.key → ms (-1 = yok)
    @Volatile var pingAt = 0L
    /** 1.43: Premium bolmasa diňe mugt serwerler (#tvfree); sanaw ýok bolsa (köne bot) — hemmesi. */
    fun allowed(ctx: Context?, s: Server): Boolean = ctx == null || (Sub.free.isEmpty() && Sub.pkeys == null) || Lic.prem(ctx) || s.hp in Sub.free   // 1.47: täze bot (#tvkp bar) — mugt sanaw boş bolsa hem Premium serwerler açylmaýar
    private fun cands(): List<Server> {
        val c = app
        if (c != null && pubg(c)) return Sub.list.filter { it.game && allowed(c, it) }   // 1.47: PUBG düwmesi
        val base = Sub.list.filter { !it.ru && !it.game && allowed(c, it) }.ifEmpty { Sub.list.filter { !it.ru && allowed(c, it) } }
        if (c == null || Sub.free.isEmpty() || !Lic.prem(c)) return base
        return if (autoPrem(c)) base.filter { it.hp !in Sub.free } else base.filter { it.hp in Sub.free }.ifEmpty { base }   // 1.46.4 (1.47: Premium-da kod ýok — bestFb mugta geçirýär)
    }

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

    @Volatile private var repAt = 0L
    /** 1.16.6: ping netijeleri bota (Telegram kanalynyň işlemeýän kodlary aýrylsyn). Iň köp 20 minutda bir;
     *  hiç bir kod jogap bermese (internet ýok bolup biler) iberilmeýär — ýalňyş «işlemeýär» diýilmesin. */
    fun report(ctx: Context) {
        val now = System.currentTimeMillis()
        if (now - repAt < 20 * 60_000L || pings.values.none { it > 0 }) return
        repAt = now
        val o = org.json.JSONObject(); pings.forEach { (k, v) -> o.put(k.substringAfter('|'), v) }
        Msg.send(ctx, org.json.JSONObject().put("k", "pr").put("p", o))
    }

    /** 1.16.7: kanal («tm») we admin («VIP») kodlary 3 minutda bir barlanýar, netije bota (3 gezek ms ýok — bot aýyrýar). */
    @Volatile private var xAt = 0L
    fun isExtra(s: Server): Boolean { val t = s.title.lowercase(); return t == "vip" || t.startsWith("vip ") }   // kanal kody («tm») täze kod gelýänçä durýar — barlanmaýar
    fun pingExtra(ctx: Context) {
        val now = System.currentTimeMillis()
        if (now - xAt < 180_000L) return
        xAt = now
        val xs = Sub.list.filter { isExtra(it) }
        if (xs.isEmpty()) return
        Thread {
            val got = ConcurrentHashMap<String, Long>()
            val pool = java.util.concurrent.Executors.newFixedThreadPool(minOf(xs.size, 4))
            xs.forEach { s -> pool.execute { got[s.key] = ping(s) } }
            pool.shutdown(); pool.awaitTermination(25, java.util.concurrent.TimeUnit.SECONDS)
            if (got.values.none { it > 0 } && !online(ctx)) return@Thread   // internet ýok — «işlemeýär» diýilmesin
            val o = org.json.JSONObject(); got.forEach { (k, v) -> o.put(k.substringAfter('|'), v) }
            Msg.send(ctx, org.json.JSONObject().put("k", "pr").put("p", o))
            Msg.events.add(org.json.JSONObject().put("k", "srv"))
        }.start()
    }

    @Volatile var dead = false     // 1.36: bagly serwer jogap bermeýär (2 gezek yzly-yzyna) — baş sahypada gyzyl duýduryş
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
    // 1.35: awtomatik serwer çalşmak aýryldy (eýesiniň islegi) — birikdirilen serweriň pingi diňe ölçenýär
    @Volatile private var hcBusy = false
    private var movedAt = 0L
    private var deadHp = ""; private var deadAt = 0L
    private var hcAt = 0L
    private var bad = 0
    private val tick = object : Runnable {
        override fun run() {
            val now0 = System.currentTimeMillis()
            if (want && State.now == State.ON && !hcBusy && now0 - hcAt > 15_000 && now0 - State.onAt > 20_000) {
                hcAt = now0; hcBusy = true; Thread { try { health() } finally { hcBusy = false } }.start()
            }
            // 1 sagat dolunca (key yoksa) VPN durur; kullanıcı elle yeniden başlatır
            if (want && State.now == State.ON && Lic.left(this@Svc) == 0L) { stop(); expired(); return }
            // 1.46.8: awtomatik saýlawda bagly serwer jogap bermeýär — 25 sn soň sanaw derrew täzelenýär we işleýän serwere geçilýär
            if (want && State.now == State.ON && State.dead && State.selected(this@Svc) == null && deadAt > 0 && now0 - deadAt > 25_000 && now0 - movedAt > 90_000) {
                movedAt = now0
                Thread { runCatching { Sub.refresh(this@Svc, 8000) }; runCatching { startService(Intent(this@Svc, Svc::class.java)) } }.start()
            }
            // 1.46.8: bagly serwer sanawdan aýryldy ýa-da indi Premium (mugt wagtlaýyn berlen serwer yzyna alyndy) — başga mugt serwere geçilýär
            val act = State.active
            if (want && State.now == State.ON && act != null && Sub.list.isNotEmpty() && now0 - movedAt > 60_000 && now0 - State.onAt > 20_000
                && (Sub.list.none { it.hp == act.hp } || !State.allowed(this@Svc, act))) {
                movedAt = now0; if (State.selected(this@Svc)?.hp == act.hp) State.select(this@Svc, null)
                runCatching { startService(Intent(this@Svc, Svc::class.java)) }
            }
            if (want && State.now == State.ON && System.currentTimeMillis() - beatAt > 5 * 60_000) {
                beatAt = System.currentTimeMillis(); Thread { Stats.beat(this@Svc, true) }.start()
            }
            if (want) h.postDelayed(this, 10_000)
        }
    }

    @Volatile private var wasOn = false   // 1.28: şu gezek birikme bolupdy (kill switch diňe şonda petikleýär)

    private fun health() {
        val c = core ?: return
        val v = runCatching { c.measureDelay(State.PING) }.getOrDefault(-1L)
        if (v in 1..2999) { State.ms = v; bad = 0; State.dead = false; return }
        if (++bad >= 2) {
            State.dead = State.online(this)   // telefonyň öz interneti ýok bolsa serwer günäkär däl
            val a = State.active   // 1.46.8: bagly serwer jogap bermeýär — bota derrew (mugt serwerler bloklananda Premium-dan biri berilsin)
            if (State.dead && a != null && (a.hp != deadHp || System.currentTimeMillis() - deadAt > 300_000L)) {
                deadHp = a.hp; deadAt = System.currentTimeMillis()
                runCatching { Msg.send(this, org.json.JSONObject().put("k", "pr").put("p", org.json.JSONObject().put(a.hp, -1))) }
            }
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
            // 1.47: birikme bar (serwer çalşylýar) — täze serwer tapylýança köne birikme kesilmeýär; tapylmasa şol galýar
            val keep = State.now == State.ON && core != null && State.active?.let { a -> State.allowed(this, a) && Sub.list.any { it.hp == a.hp } } == true
            if (!keep) stopLoop()   // 1.28: köne tunel täzesi açylýança ýapylmaýar — arada gorag ýok ýagdaý bolmasyn
            // 1.16: her birikmede ilki abuna täzelenýär (iň köp 5 sn). Gijä galsa — häzirki sanawdan iň çalt jogap bereni saýlanýar
            val app = applicationContext
            val th = Thread { runCatching { if (Sub.refresh(app, 5000)) Msg.events.add(org.json.JSONObject().put("k", "srv")) } }.apply { isDaemon = true; start() }
            th.join(5000)
            val slow = th.isAlive
            if (Sub.list.isEmpty()) Sub.load(this)
            if (!want || g != gen) return
            val sel = State.selected(this)   // 1.35: saýlanan serwer — abuna gijä galsa-da başga serwere geçilmeýär
            if (sel != null && !State.online(this)) { State.noNet = true; throw IllegalStateException("internet yok") }
            val s = sel ?: State.bestFb(this) ?: if (keep) return else throw IllegalStateException("ping yok")
            if (keep) stopLoop()
            State.noPing = false; State.noNet = false; State.ms = 0; State.dead = false; bad = 0
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
            val old = tun; tun = fd; if (old != null && old !== fd) runCatching { old.close() }
            State.hold = false
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
            State.set(State.ON); wasOn = true
            Msg.start(applicationContext); Msg.kick()
            runCatching { getSystemService(NotificationManager::class.java).notify(1, note(s)) }   // bildirim: «Birikdirildi · ülke»
            if (slow) Thread { if (System.currentTimeMillis() - Sub.okAt > 60_000) Sub.refresh(app) }.start()
        } catch (e: Throwable) {
            if (!want || g != gen) { stopLoop(); return }   // kullanıcı iptal etti ya da yeni bağlantı istendi
            if (wasOn && Lic.kill(this)) { holdBlock(); return }   // 1.28: kill switch — internet ýapyk galýar
            stopCore()
            State.set(State.FAIL)
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private fun stopLoop() {
        State.core = null; State.socks = 0
        runCatching { core?.stopLoop() }
        core = null
    }

    private fun stopCore() {
        stopLoop()
        runCatching { tun?.close() }
        tun = null; State.hold = false
    }

    /** 1.28: kill switch — VPN kesildi: tunel açyk galýar, ýöne hiç zat geçirmeýär (internet ýapyk), ulanyjy täzeden birikýänçä ýa-da öçürýänçä. */
    private fun holdBlock() {
        stopLoop()
        if (tun == null) runCatching {
            val b = Builder().setSession(getString(R.string.app_name)).setMtu(1500)
                .addAddress("172.19.0.1", 30).addRoute("0.0.0.0", 0).addAddress("fdfe:dcba:9876::1", 126).addRoute("::", 0)
            b.addDisallowedApplication(packageName)
            tun = b.establish()
        }
        State.hold = true
        State.set(State.FAIL)
        runCatching { getSystemService(NotificationManager::class.java).notify(1, holdNote()) }
    }

    private fun holdNote(): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val off = PendingIntent.getService(this, 1, Intent(this, Svc::class.java).setAction(STOP), PendingIntent.FLAG_IMMUTABLE)
        val nb = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, "v") else Notification.Builder(this)
        val txt = t("VPN kesildi — internet ýapyk (Kill switch). Täzeden birigiň ýa-da öçüriň.", "VPN оборвался — интернет закрыт (Kill switch). Подключитесь снова или отключите.",
            "VPN koptu — internet kapalı (Kill switch). Yeniden bağlanın ya da kapatın.")
        return nb.setSmallIcon(R.drawable.ic_notif).setContentTitle(getString(R.string.app_name)).setContentText(txt)
            .setStyle(Notification.BigTextStyle().bigText(txt)).setContentIntent(open).setOngoing(true)
            .addAction(Notification.Action.Builder(null, t("Interneti aç", "Открыть интернет", "İnterneti aç"), off).build()).build()
    }

    private fun stop() {
        want = false; gen++; wasOn = false; State.dead = false
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
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
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
        val open = PendingIntent.getActivity(this, 4, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val nb = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, "e") else Notification.Builder(this)
        val txt = t("Mugt wagt doldy, VPN öçdi. Dowam etmek üçin täzeden birikiň ýa-da açar alyň.", "Бесплатное время истекло, VPN отключён. Подключитесь снова или купите ключ.",
            "Ücretsiz süre doldu, VPN kapandı. Yeniden bağlanın ya da anahtar alın.")
        nm.notify(3, nb.setSmallIcon(R.drawable.ic_notif).setContentTitle(getString(R.string.app_name)).setContentText(txt)
            .setStyle(Notification.BigTextStyle().bigText(txt)).setContentIntent(open).setAutoCancel(true).build())
    }

    companion object {
        const val STOP = "stop"

        /** Programma ýapykka admin jogap berse: bildiriş. */
        /** Admin telefonyna: täze bilet / habar (1.16.4 — Telegram bot deregine). */
        fun notifyAdmin(ctx: Context, tid: Int, who: String, text: String) = runCatching {
            val nm = ctx.getSystemService(NotificationManager::class.java)
            if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(NotificationChannel("a", t("Biletler (admin)", "Тикеты (админ)", "Biletler (yönetici)"), NotificationManager.IMPORTANCE_HIGH))
            val open = PendingIntent.getActivity(ctx, 7, Intent(ctx, MainActivity::class.java).setAction(Main.ADMT).putExtra("tid", tid), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val nb = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(ctx, "a") else Notification.Builder(ctx)
            nm.notify(100 + (tid % 1000), nb.setSmallIcon(R.drawable.ic_notif).setContentTitle("🎫 #$tid · $who").setContentText(text.take(200))
                .setStyle(Notification.BigTextStyle().bigText(text.take(500))).setContentIntent(open).setAutoCancel(true).build())
        }

        fun notifyPreq(ctx: Context, who: String, plan: String) = runCatching {   // 1.44
            val nm = ctx.getSystemService(NotificationManager::class.java)
            if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(NotificationChannel("p", t("Premium aljaklar", "Покупатели Premium", "Premium alıcıları"), NotificationManager.IMPORTANCE_HIGH))
            val open = PendingIntent.getActivity(ctx, 9, Intent(ctx, MainActivity::class.java).setAction(Main.PREQ), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val nb = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(ctx, "p") else Notification.Builder(ctx)
            val pl = if (plan == "y") t("1 ýyl", "1 год", "1 yıl") else t("1 aý", "1 месяц", "1 ay")
            nm.notify(300 + (who.hashCode() and 0xff), nb.setSmallIcon(R.drawable.ic_notif).setContentTitle("👑 " + t("Premium aljak", "Хочет Premium", "Premium alıcı") + " · $who")
                .setContentText(pl).setContentIntent(open).setAutoCancel(true).build())
        }

        fun notifyReply(ctx: Context, text: String) = runCatching {
            val nm = ctx.getSystemService(NotificationManager::class.java)
            if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(NotificationChannel("m", t("Admin jogaby", "Ответ админа", "Yönetici yanıtı"), NotificationManager.IMPORTANCE_DEFAULT))
            val open = PendingIntent.getActivity(ctx, 5, Intent(ctx, MainActivity::class.java).setAction(Main.CHAT), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val nb = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(ctx, "m") else Notification.Builder(ctx)
            val title = "💬 " + t("Admin jogap berdi", "Ответ админа", "Yönetici yanıtladı")
            nm.notify(6, nb.setSmallIcon(R.drawable.ic_notif).setContentTitle(title).setContentText(text.take(200))
                .setStyle(Notification.BigTextStyle().bigText(text.take(500))).setContentIntent(open).setAutoCancel(true).build())
        }
    }
}
