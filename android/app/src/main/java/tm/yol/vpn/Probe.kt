package tm.yol.vpn

import android.content.Context
import libv2ray.Libv2ray
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * 1.46: Türkmenistanyň interneti bilen kod barlagy. Bot tapan kodlary (n/probe) programma açyk wagty
 * arka fonda birnäçesini synap görýär we netijäni bota iberýär — diňe Türkmenistanda işleýänler sanawa goşulýar.
 * Bu kodlar sanawda görkezilmeýär; her synag diňe bir gysga HTTP soragy (birnäçe KB).
 * 1.46.3: n/probe — gyssagly kodlar (bir gezek işlän / sanawdaky köne) + iň gowy täzeler; galan täzeler bölek-bölek
 * (n/probe1…k) — telefon diňe bir bölegi okaýar (az trafik). VPN açyk wagty fonda hem (30 minutda bir, az kod).
 */
object Probe {
    @Volatile private var at = 0L
    @Volatile var busy = false

    private fun codes(raw: String?): List<String> {
        val arr = runCatching { JSONObject(raw ?: return emptyList()).optJSONArray("c") }.getOrNull() ?: JSONArray()
        return (0 until arr.length()).map { arr.optString(it) }.filter { it.contains("://") }
    }

    /** Synaljak kodlar: ýarysy gyssaglylardan, galany täzelerden (tötänleýin bölek). */
    private fun pick(n: Int): List<String> {
        val raw = Fs.get("n/probe", 6000)?.first?.let { Msg.dec(it) ?: it } ?: return emptyList()
        val head = codes(raw)
        val o = runCatching { JSONObject(raw) }.getOrNull()
        val u = (o?.optInt("u", 0) ?: 0).coerceIn(0, head.size)
        val k = o?.optInt("k", 0) ?: 0
        val urg = head.take(u).shuffled()
        var rest = head.drop(u)
        if (k > 0) {
            val i = (1..k).random()
            rest = rest + codes(Fs.get("n/probe$i", 6000)?.first?.let { Msg.dec(it) ?: it })
        }
        val a = urg.take(maxOf(n / 2, n - rest.size))
        return (a + rest.shuffled().take(n - a.size)).distinct()
    }

    /** n: näçe kod; force: wagta seretmezden (eýesiniň düwmesi); every: iki synagyň arasy. Dönüş: başlandymy. */
    fun run(ctx: Context, n: Int = 20, force: Boolean = false, every: Long = 10 * 60_000L, done: ((Int, Int) -> Unit)? = null): Boolean {
        val now = System.currentTimeMillis()
        if (busy || !Fs.vps() || (!force && now - at < every)) return false
        at = now; busy = true
        Thread {
            var tested = 0; var ok = 0
            try {
                val codes = pick(n)
                if (codes.isEmpty() || !State.online(ctx)) return@Thread
                val got = ConcurrentHashMap<String, Long>()
                val pool = Executors.newFixedThreadPool(6)
                codes.forEach { c -> pool.execute {
                    val hp = runCatching { Cfg.link(c).let { "${it.host}:${it.port}" } }.getOrNull() ?: return@execute
                    got[hp] = runCatching { Libv2ray.measureOutboundDelay(Cfg.full(c, false), State.PING) }.getOrDefault(-1L)
                } }
                pool.shutdown(); pool.awaitTermination(maxOf(30L, n * 3L), TimeUnit.SECONDS)
                if (got.values.none { it > 0 } && !State.online(ctx)) return@Thread   // internet ýok — «işlemeýär» diýilmesin
                tested = got.size; ok = got.values.count { it > 0 }
                got.entries.chunked(70).forEach { part ->
                    val o = JSONObject(); part.forEach { (k, v) -> o.put(k, v) }
                    Msg.send(ctx, JSONObject().put("k", "pr").put("p", o))
                }
            } finally { busy = false; done?.invoke(tested, ok) }
        }.apply { isDaemon = true }.start()
        return true
    }
}
