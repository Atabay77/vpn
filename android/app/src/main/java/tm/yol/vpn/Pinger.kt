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

    // 1.47.32: doly barlag — her serwer üçin goşmaça girişler: DNS (TCP 1.1.1.1:53 — VPN-iň DNS-i ýaly), çykyş ýurdy (ip-api), ýükleme tizligi (100 KB)
    const val CC_HOST = "ip-api.com"; const val CC_PATH = "/line/?fields=countryCode"
    const val DL_HOST = "cachefly.cachefly.net"; const val DL_PATH = "/100kb.test"
    private val EXTRA = listOf("d" to ("1.1.1.1" to 53), "c" to (CC_HOST to 80), "s" to (DL_HOST to 80))

    /** Xray sazlamasy: i<n> giriş → o<n> çykyş. Goldanmaýan kod — geçilýär. Dönüş: (sazlama, [serweriň belgisi → port]).
     *  full — her serwer üçin 4 port (ping, DNS, ýurt, tizlik): ports[i*4 .. i*4+3]. */
    fun config(list: List<Server>, ports: IntArray, host: String = HOST, port: Int = 80, full: Boolean = false): Pair<String, Map<Int, Int>> {
        val ins = JSONArray(); val outs = JSONArray(); val rules = JSONArray(); val used = HashMap<Int, Int>()
        list.forEachIndexed { i, s ->
            val ob = runCatching { Cfg.outbound(s.uri) }.getOrNull() ?: return@forEachIndexed
            ob.put("tag", "o$i"); outs.put(ob)
            val p0 = if (full) ports[i * 4] else ports[i]
            ins.put(JSONObject().put("tag", "i$i").put("protocol", "dokodemo-door").put("listen", "127.0.0.1").put("port", p0)
                .put("settings", JSONObject().put("address", host).put("port", port).put("network", "tcp")))
            val tags = JSONArray().put("i$i")
            if (full) EXTRA.forEachIndexed { k, (t, hp) ->
                ins.put(JSONObject().put("tag", "$t$i").put("protocol", "dokodemo-door").put("listen", "127.0.0.1").put("port", ports[i * 4 + 1 + k])
                    .put("settings", JSONObject().put("address", hp.first).put("port", hp.second).put("network", "tcp")))
                tags.put("$t$i")
            }
            rules.put(JSONObject().put("type", "field").put("inboundTag", tags).put("outboundTag", "o$i"))
            used[i] = p0
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

    /** Doly barlagyň netijesi. ok — saýtlar açylar (ms bar, DNS işleýär, ýükleme bolýar). */
    data class Full(val ms: Long, val dns: Boolean, val cc: String, val kbps: Int) {
        val ok get() = ms > 0 && dns && kbps >= MIN_KBPS
    }
    const val MIN_KBPS = 15   // 100 KB-dan haýal ýüklenýän serwer — «hiç zat açylmaýar» diýip hasaplanýar

    /** DNS-over-TCP (2 baýt uzynlyk + sorag) — jogapda A ýazgysy barmy. */
    fun tcpDns(port: Int, timeoutMs: Int = 5000): Boolean = runCatching {
        Socket().use { so ->
            so.connect(InetSocketAddress("127.0.0.1", port), 1000); so.soTimeout = timeoutMs
            val id = (System.nanoTime() and 0xffff).toInt(); val q = Dns.query("www.google.com", id)
            val out = so.getOutputStream(); out.write(byteArrayOf((q.size shr 8).toByte(), q.size.toByte())); out.write(q); out.flush()
            val inp = java.io.DataInputStream(so.getInputStream())
            val n = inp.readUnsignedShort(); if (n < 12 || n > 4096) return@use false
            val b = ByteArray(n); inp.readFully(b); Dns.answered(b, n, id)
        }
    }.getOrDefault(false)

    /** Ýönekeý HTTP GET (bir birikme) — jogabyň bedeni (iň köp max baýt) we wagty. */
    private fun httpGet(port: Int, host: String, path: String, max: Int, timeoutMs: Int): Pair<ByteArray, Long>? = runCatching {
        Socket().use { so ->
            so.connect(InetSocketAddress("127.0.0.1", port), 1000); so.soTimeout = timeoutMs
            val t0 = System.nanoTime()
            so.getOutputStream().apply { write("GET $path HTTP/1.1\r\nHost: $host\r\nUser-Agent: Mozilla/5.0\r\nConnection: close\r\n\r\n".toByteArray()); flush() }
            val all = java.io.ByteArrayOutputStream(); val buf = ByteArray(16384); val inp = so.getInputStream()
            val end = System.currentTimeMillis() + timeoutMs
            while (all.size() < max + 2048 && System.currentTimeMillis() < end) { val n = inp.read(buf); if (n < 0) break; all.write(buf, 0, n) }
            val raw = all.toByteArray(); var h = -1
            for (i in 0 until raw.size - 3) if (raw[i] == 13.toByte() && raw[i + 1] == 10.toByte() && raw[i + 2] == 13.toByte() && raw[i + 3] == 10.toByte()) { h = i + 4; break }
            if (h < 0 || !String(raw, 0, minOf(h, 16)).startsWith("HTTP/1.1 2") && !String(raw, 0, minOf(h, 16)).startsWith("HTTP/1.0 2")) return@use null
            raw.copyOfRange(h, raw.size) to (System.nanoTime() - t0) / 1_000_000
        }
    }.getOrNull()

    fun fullCheck(ports: IntArray, base: Int): Full {
        val ms = measure(ports[base])
        if (ms <= 0) return Full(-1, false, "", -1)
        val dns = tcpDns(ports[base + 1]) || tcpDns(ports[base + 1])
        val cc = httpGet(ports[base + 2], CC_HOST, CC_PATH, 64, 6000)?.first?.toString(Charsets.UTF_8)?.trim()?.uppercase()?.takeIf { Regex("^[A-Z]{2}$").matches(it) } ?: ""
        val dl = httpGet(ports[base + 3], DL_HOST, DL_PATH, 102400, 9000)
        val kbps = if (dl == null || dl.first.size < 50_000) -1 else (dl.first.size * 1000L / 1024 / maxOf(1L, dl.second)).toInt()
        return Full(ms, dns, cc, kbps)
    }

    /** 1.47.32: doly barlag (birikmezden öň): ping + DNS + ýurt + 100 KB ýükleme. each — her netije. Dönüş null — Xray açylmady / başga barlag bar. */
    fun runFull(list: List<Server>, parallel: Int = 8, maxWaitMs: Long = 60_000, each: ((Server, Full) -> Unit)? = null): Map<String, Full>? {
        if (list.isEmpty()) return emptyMap()
        if (!busy.compareAndSet(false, true)) return null
        val res = ConcurrentHashMap<String, Full>(); var core: libv2ray.CoreController? = null
        try {
            val ports = freePorts(list.size * 4)
            val (cfg, used) = config(list, ports, full = true)
            if (used.isEmpty()) return res
            core = Libv2ray.newCoreController(object : CoreCallbackHandler {
                override fun startup(): Long = 0
                override fun shutdown(): Long = 0
                override fun onEmitStatus(p0: Long, p1: String?): Long = 0
            })
            core.startLoop(cfg, 0)
            val p0 = used.values.first(); val t0 = System.currentTimeMillis()
            while (System.currentTimeMillis() - t0 < 2500) {
                if (runCatching { Socket().use { it.connect(InetSocketAddress("127.0.0.1", p0), 200) }; true }.getOrDefault(false)) break
                Thread.sleep(40)
            }
            val pool = Executors.newFixedThreadPool(minOf(parallel, used.size))
            used.keys.forEach { i -> val s = list[i]; pool.execute { val f = fullCheck(ports, i * 4); res[s.key] = f; runCatching { each?.invoke(s, f) } } }
            pool.shutdown()
            pool.awaitTermination(maxWaitMs, TimeUnit.MILLISECONDS); pool.shutdownNow()
            return res
        } catch (e: Throwable) { return if (res.isEmpty()) null else res
        } finally { runCatching { core?.stopLoop() }; busy.set(false) }
    }

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
