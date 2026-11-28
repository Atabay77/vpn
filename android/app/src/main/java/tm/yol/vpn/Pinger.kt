package tm.yol.vpn

import libv2ray.CoreCallbackHandler
import libv2ray.Libv2ray
import org.json.JSONArray
import org.json.JSONObject
import java.io.InputStream
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 1.47.31: Happ ýaly çalt ping — «via Proxy GET · KeepAlive».
 * Ähli serwerler üçin BIR Xray (öň her serwer üçin aýratyn Xray açylýardy: haýal, gowşak telefonlarda «n/a»).
 * Her serwere öz ýerli girişi (dokodemo-door → www.gstatic.com:80), şol bir birikmede iki HTTP sorag:
 * birinjisi birikmäni gurýar, ikinjisi arassa gidip-gelme wagtyny ölçeýär; iň gowusy alynýar.
 */
object Pinger {
    const val HOST = "www.gstatic.com"; const val PATH = "/generate_204"
    private val busy = AtomicBoolean(false)

    /** Xray sazlamasy: i<n> giriş → o<n> çykyş. Goldanmaýan kod — geçilýär. Dönüş: (sazlama, [serweriň belgisi → port]). */
    fun config(list: List<Server>, ports: IntArray, host: String = HOST, port: Int = 80): Pair<String, Map<Int, Int>> {
        val ins = JSONArray(); val outs = JSONArray(); val rules = JSONArray(); val used = HashMap<Int, Int>()
        list.forEachIndexed { i, s ->
            val ob = runCatching { Cfg.outbound(s.uri) }.getOrNull() ?: return@forEachIndexed
            ob.put("tag", "o$i"); outs.put(ob)
            ins.put(JSONObject().put("tag", "i$i").put("protocol", "dokodemo-door").put("listen", "127.0.0.1").put("port", ports[i])
                .put("settings", JSONObject().put("address", host).put("port", port).put("network", "tcp")))
            rules.put(JSONObject().put("type", "field").put("inboundTag", JSONArray().put("i$i")).put("outboundTag", "o$i"))
            used[i] = ports[i]
        }
        outs.put(JSONObject().put("tag", "direct").put("protocol", "freedom"))
        val c = JSONObject().put("log", JSONObject().put("loglevel", "none")).put("inbounds", ins).put("outbounds", outs)
            .put("routing", JSONObject().put("domainStrategy", "AsIs").put("rules", rules))
        return c.toString() to used
    }

    /** Bir HTTP jogabyň başlygy: status kody (body bolsa okalýar). -1 — ýalňyş. */
    fun readResp(inp: InputStream): Int {
        val sb = StringBuilder(); var last4 = 0
        while (true) {
            val b = inp.read(); if (b < 0) return -1
            sb.append(b.toChar()); last4 = (last4 shl 8) or b
            if (last4 == 0x0d0a0d0a) break
            if (sb.length > 8192) return -1
        }
        val head = sb.toString()
        val code = Regex("^HTTP/1\\.[01] (\\d{3})").find(head)?.groupValues?.get(1)?.toIntOrNull() ?: return -1
        val len = Regex("(?im)^content-length:\\s*(\\d+)").find(head)?.groupValues?.get(1)?.toLongOrNull() ?: 0L
        var left = len
        while (left > 0) { val n = inp.skip(left); if (n <= 0) { if (inp.read() < 0) return -1; left-- } else left -= n }
        return code
    }

    /** Ýerli porta iki sorag (KeepAlive). Dönüş: ms ýa-da -1. */
    fun measure(port: Int, host: String = HOST, path: String = PATH, firstMs: Int = 5000, secondMs: Int = 3000): Long = runCatching {
        Socket().use { so ->
            so.tcpNoDelay = true
            so.connect(InetSocketAddress("127.0.0.1", port), 1000)
            val req = "GET $path HTTP/1.1\r\nHost: $host\r\nUser-Agent: Mozilla/5.0\r\nAccept: */*\r\nConnection: keep-alive\r\n\r\n".toByteArray()
            val out = so.getOutputStream(); val inp = so.getInputStream().buffered()
            so.soTimeout = firstMs
            var t0 = System.nanoTime(); out.write(req); out.flush()
            val c1 = readResp(inp); val r1 = (System.nanoTime() - t0) / 1_000_000
            if (c1 !in 200..399) return@use -1L
            so.soTimeout = secondMs
            t0 = System.nanoTime()
            val r2 = runCatching { out.write(req); out.flush(); if (readResp(inp) in 200..399) (System.nanoTime() - t0) / 1_000_000 else -1L }.getOrDefault(-1L)
            maxOf(1L, if (r2 >= 0) minOf(r1, r2) else r1)
        }
    }.getOrDefault(-1L)

    private fun freePorts(n: Int): IntArray {
        val socks = (0 until n).map { ServerSocket(0) }
        return try { socks.map { it.localPort }.toIntArray() } finally { socks.forEach { runCatching { it.close() } } }
    }

    /**
     * Ähli serwerleri ölçeýär. each — her netije gelende (UI täzelenmesi). stop — true dolansa galanlary garaşylmaýar
     * (meselem 200 ms-den az ilkinji serwer tapyldy). Dönüş: {server.key → ms}; Xray açylmasa null (köne usul ulanylsyn).
     */
    fun run(list: List<Server>, host: String = HOST, path: String = PATH, parallel: Int = 16, maxWaitMs: Long = 9000,
            each: ((Server, Long) -> Unit)? = null, stop: ((Server, Long) -> Boolean)? = null): Map<String, Long>? {
        if (list.isEmpty()) return emptyMap()
        if (!busy.compareAndSet(false, true)) return null
        val res = ConcurrentHashMap<String, Long>()
        var core: libv2ray.CoreController? = null
        try {
            val ports = freePorts(list.size)
            val (cfg, used) = config(list, ports, host)
            if (used.isEmpty()) return res
            core = Libv2ray.newCoreController(object : CoreCallbackHandler {
                override fun startup(): Long = 0
                override fun shutdown(): Long = 0
                override fun onEmitStatus(p0: Long, p1: String?): Long = 0
            })
            core.startLoop(cfg, 0)
            val p0 = used.values.first(); val t0 = System.currentTimeMillis()
            while (System.currentTimeMillis() - t0 < 2500) {   // Xray açylan badyna
                if (runCatching { Socket().use { it.connect(InetSocketAddress("127.0.0.1", p0), 200) }; true }.getOrDefault(false)) break
                Thread.sleep(40)
            }
            val done = AtomicBoolean(false)
            val pool = Executors.newFixedThreadPool(minOf(parallel, used.size))
            used.forEach { (i, port) ->
                val s = list[i]
                pool.execute {
                    if (done.get()) return@execute
                    val ms = measure(port, host, path)
                    res[s.key] = ms
                    runCatching { each?.invoke(s, ms) }
                    if (stop != null && runCatching { stop(s, ms) }.getOrDefault(false)) done.set(true)
                }
            }
            pool.shutdown()
            val end = System.currentTimeMillis() + maxWaitMs
            while (!pool.isTerminated && !done.get() && System.currentTimeMillis() < end) pool.awaitTermination(50, TimeUnit.MILLISECONDS)
            pool.shutdownNow()
            return res
        } catch (e: Throwable) {
            return if (res.isEmpty()) null else res
        } finally {
            runCatching { core?.stopLoop() }
            busy.set(false)
        }
    }
}
