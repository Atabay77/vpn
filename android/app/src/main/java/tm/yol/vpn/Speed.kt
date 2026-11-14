package tm.yol.vpn

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.Proxy
import java.net.URL
import java.util.concurrent.atomic.AtomicLong

/** 1.19: tizlik synagy. VPN birikdirilen bolsa tüneliň içinden (programmanyň öz SOCKS porty arkaly), ýogsa göni internetden. */
object Speed {
    @Volatile var busy = false
    private const val DL = "https://speed.cloudflare.com/__down?bytes=60000000"
    private const val UL = "https://speed.cloudflare.com/__up"

    private fun ev(o: JSONObject) = Msg.events.add(o.put("k", "spd"))
    private fun mbps(bytes: Long, ms: Long) = if (ms <= 0) 0.0 else bytes * 8.0 / ms / 1000.0

    fun run() {
        if (busy) return
        busy = true
        try {
            val sp = State.socks
            val px = if (State.now == State.ON && sp > 0) Proxy(Proxy.Type.SOCKS, InetSocketAddress("127.0.0.1", sp)) else Proxy.NO_PROXY
            val via = px != Proxy.NO_PROXY
            ev(JSONObject().put("ph", "ping").put("via", via))
            val ping = if (via) runCatching { State.core?.measureDelay(State.PING) ?: -1L }.getOrDefault(-1L) else direct()
            ev(JSONObject().put("ph", "dl").put("ping", ping))
            val dl = transfer(px, true, 8000)
            ev(JSONObject().put("ph", "ul").put("ping", ping).put("dl", dl))
            val ul = transfer(px, false, 6000)
            ev(JSONObject().put("ph", "done").put("ping", ping).put("dl", dl).put("ul", ul).put("via", via))
        } catch (e: Throwable) {
            ev(JSONObject().put("ph", "err"))
        } finally { busy = false }
    }

    private fun direct(): Long {
        var best = -1L
        repeat(3) {
            val t0 = System.currentTimeMillis()
            val ok = runCatching { (URL("https://www.googleapis.com/generate_204").openConnection() as HttpURLConnection).run { connectTimeout = 4000; readTimeout = 4000; try { responseCode > 0 } finally { disconnect() } } }.getOrDefault(false)
            val d = System.currentTimeMillis() - t0
            if (ok && (best < 0 || d < best)) best = d
        }
        return best
    }

    /** 3 parallel akym; her 500 ms-da aralyk netije. Netije: Mbit/s (0 = başartmady). */
    private fun transfer(px: Proxy, down: Boolean, limit: Long): Double {
        val total = AtomicLong(0); val t0 = System.currentTimeMillis(); val end = t0 + limit
        val th = (1..3).map {
            Thread {
                runCatching {
                    val c = URL(if (down) DL else UL).openConnection(px) as HttpURLConnection
                    c.connectTimeout = 6000; c.readTimeout = 6000
                    try {
                        if (down) {
                            val buf = ByteArray(64 * 1024)
                            c.inputStream.use { ins -> while (System.currentTimeMillis() < end) { val n = ins.read(buf); if (n < 0) break; total.addAndGet(n.toLong()) } }
                        } else {
                            c.doOutput = true; c.requestMethod = "POST"; c.setChunkedStreamingMode(64 * 1024)
                            val buf = ByteArray(64 * 1024).also { java.util.Random().nextBytes(it) }
                            c.outputStream.use { o -> while (System.currentTimeMillis() < end) { o.write(buf); total.addAndGet(buf.size.toLong()) } }
                            runCatching { c.responseCode }
                        }
                    } finally { c.disconnect() }
                }
            }.apply { isDaemon = true; start() }
        }
        while (System.currentTimeMillis() < end && th.any { it.isAlive }) {
            Thread.sleep(500)
            ev(JSONObject().put("ph", if (down) "dl" else "ul").put("live", mbps(total.get(), System.currentTimeMillis() - t0)).put("p", ((System.currentTimeMillis() - t0) * 100 / limit).coerceAtMost(100)))
        }
        th.forEach { it.join(1500) }
        return mbps(total.get(), (System.currentTimeMillis() - t0).coerceAtMost(limit + 1500))
    }
}
