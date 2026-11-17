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
 */
object Probe {
    @Volatile private var at = 0L
    @Volatile var busy = false

    /** n: näçe kod; force: wagta seretmezden (eýesiniň düwmesi). Dönüş: başlandymy. */
    fun run(ctx: Context, n: Int = 12, force: Boolean = false, done: ((Int, Int) -> Unit)? = null): Boolean {
        val now = System.currentTimeMillis()
        if (busy || !Fs.vps() || (!force && now - at < 20 * 60_000L)) return false
        at = now; busy = true
        Thread {
            var tested = 0; var ok = 0
            try {
                val raw = Fs.get("n/probe", 6000)?.first?.let { Msg.dec(it) ?: it } ?: return@Thread
                val arr = runCatching { JSONObject(raw).optJSONArray("c") }.getOrNull() ?: JSONArray()
                val codes = (0 until arr.length()).map { arr.optString(it) }.filter { it.contains("://") }.shuffled().take(n)
                if (codes.isEmpty() || !State.online(ctx)) return@Thread
                val got = ConcurrentHashMap<String, Long>()
                val pool = Executors.newFixedThreadPool(4)
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
