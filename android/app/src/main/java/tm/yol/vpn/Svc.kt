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

    @Volatile var active: Server? = null      // şu an bağlı olunan sunucu (otomatikte seçilen)

    /** Varsayılan otomatik. Elle seçilen sunucu listeden kalkarsa yine otomatiğe döner. */
    fun auto(ctx: Context) = selected(ctx) == null
    fun selected(ctx: Context): Server? {
        val k = ctx.getSharedPreferences("p", 0).getString("sel", AUTO)
        return if (k == AUTO) null else Sub.list.firstOrNull { it.key == k }
    }
    fun select(ctx: Context, s: Server?) =
        ctx.getSharedPreferences("p", 0).edit().putString("sel", s?.key ?: AUTO).apply()
    private const val AUTO = "auto"

    /** Otomatik: Rusya ve oyun sunucuları hariç, en düşük ms veren. En çok ~7 sn beklenir. */
    fun best(): Server? {
        val c = Sub.list.filter { !it.ru && !it.game }.ifEmpty { Sub.list.filter { !it.ru } }
        if (c.size <= 1) return c.firstOrNull()
        val ms = java.util.concurrent.ConcurrentHashMap<Server, Long>()
        val pool = java.util.concurrent.Executors.newFixedThreadPool(minOf(c.size, 8))
        for (s in c) pool.execute {
            runCatching { Libv2ray.measureOutboundDelay(Cfg.full(s.uri, false), PING) }
                .getOrNull()?.takeIf { it > 0 }?.let { ms[s] = it }
        }
        pool.shutdown()
        val end = System.currentTimeMillis() + 7000
        while (System.currentTimeMillis() < end && !pool.isTerminated) {
            if (ms.size == c.size) break
            Thread.sleep(150)
            // ilk sonuçtan sonra kısa süre daha bekle, daha iyisi gelebilir
            if (ms.isNotEmpty() && System.currentTimeMillis() > end - 4000) break
        }
        pool.shutdownNow()
        return ms.minByOrNull { it.value }?.key ?: c.first()
    }
    const val PING = "https://www.gstatic.com/generate_204"
}

class Svc : VpnService() {
    private var tun: ParcelFileDescriptor? = null
    private var core: CoreController? = null
    private val lock = Any()
    @Volatile private var want = false
    private val h = Handler(Looper.getMainLooper())
    private val tick = object : Runnable {
        override fun run() {
            // 2 saat dolunca (key yoksa) VPN durur; kullanıcı elle yeniden başlatır
            if (want && State.now == State.ON && Lic.left(this@Svc) == 0L) { stop(); return }
            if (want) h.postDelayed(this, 10_000)
        }
    }

    override fun onCreate() { super.onCreate(); State.app = applicationContext }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == STOP) { stop(); return START_NOT_STICKY }
        foreground()
        val reconnect = State.now == State.ON && Lic.start(this) > 0   // sunucu değiştirmek süreyi sıfırlamaz
        if (!reconnect) Lic.setStart(this, 0)
        want = true
        State.set(State.WAIT)
        h.removeCallbacks(tick); h.post(tick)
        Thread { start() }.start()
        return START_NOT_STICKY
    }

    private fun start() = synchronized(lock) {
        if (!want) return
        try {
            stopCore()
            Sub.refresh(this, 6000)            // her bağlanmada sessiz güncelleme (olmazsa önbellek)
            val s = State.selected(this) ?: State.best() ?: throw IllegalStateException("liste boş")
            State.active = s
            val cfg = Cfg.full(s.uri, true)
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
            if (!want) { stopCore(); return }
            if (Lic.start(this) == 0L) Lic.setStart(this, System.currentTimeMillis())   // 2 saat bağlanınca başlar
            State.set(State.ON)
        } catch (e: Throwable) {
            stopCore()
            State.set(State.FAIL)
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private fun stopCore() {
        runCatching { core?.stopLoop() }
        core = null
        runCatching { tun?.close() }
        tun = null
    }

    private fun stop() {
        want = false
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
        val open = PendingIntent.getActivity(this, 0, Intent(this, Main::class.java), PendingIntent.FLAG_IMMUTABLE)
        val off = PendingIntent.getService(this, 1, Intent(this, Svc::class.java).setAction(STOP), PendingIntent.FLAG_IMMUTABLE)
        val nb = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, "v") else Notification.Builder(this)
        val n = nb.setSmallIcon(R.drawable.ic_gol).setContentTitle(getString(R.string.app_name))
            .setContentText("Birikdirildi").setContentIntent(open).setOngoing(true)
            .addAction(Notification.Action.Builder(null, "Öçür", off).build()).build()
        if (Build.VERSION.SDK_INT >= 34) startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        else startForeground(1, n)
    }

    companion object { const val STOP = "stop" }
}
