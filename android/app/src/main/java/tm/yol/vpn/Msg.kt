package tm.yol.vpn

import android.annotation.SuppressLint
import android.content.Context
import android.provider.Settings
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.Proxy
import java.net.URL
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.concurrent.ConcurrentLinkedQueue
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * Bot bilen habarlaşma (ntfy.sh arkaly). Habarlar şifrelenýär: açar programmanyň Drive faýlynyň kimliginden alynýar,
 * bot hem şol bir açary hasaplaýar. VPN birikende habarlar tunel içinden gidýär (göni ýol ýapyk bolup biler);
 * birikmedik wagty göni synanyşylýar, bolmasa nobatda garaşýar.
 *
 * Konular: <T>m — bota, <T>d<dev> — şu telefona, <T>g — Global chat.
 */
object Msg {
    /** Habar serweri: VPS (abunadaky #tvrel) ýa-da ntfy.sh. */
    private fun host() = (Sub.relay.ifEmpty { "https://ntfy.sh" }) + "/"
    @Volatile var app: Context? = null
    @Volatile private var started = false
    @Volatile var watchG = false            // Global chat açyk: ýygy-ýygydan barla
    @Volatile var visible = false           // programma ekranda
    val events = ConcurrentLinkedQueue<JSONObject>()   // ekrana berilýän wakalar (JS alýar)
    private val rnd = SecureRandom()

    // ---- açarlar / konular ----
    private fun fid(): String? = runCatching { Regex("/files/([\\w-]+)").find(N.u())!!.groupValues[1] }.getOrNull()
    private fun sha(s: String) = MessageDigest.getInstance("SHA-256").digest(s.toByteArray())
    private fun hex(b: ByteArray) = b.joinToString("") { "%02x".format(it) }
    private val base: String? by lazy { fid()?.let { "tvpn" + hex(sha(it)).take(16) } }
    private val F: String? by lazy { fid() }
    fun topicBot() = base?.let { it + "m" }
    fun topicMe(ctx: Context) = base?.let { it + "d" + dev(ctx) }
    fun topicG() = base?.let { it + "g" }

    /** Telefonyň kimligi (programmany pozup gaýtadan gurnanda hem üýtgemeýär). */
    @SuppressLint("HardwareIds")
    fun dev(ctx: Context): String {
        val p = ctx.getSharedPreferences("p", 0)
        p.getString("dev", null)?.let { return it }
        val aid = runCatching { Settings.Secure.getString(ctx.contentResolver, Settings.Secure.ANDROID_ID) }.getOrNull()
        val d = hex(sha("tvdev|" + (aid ?: java.util.UUID.randomUUID().toString()))).take(12)
        p.edit().putString("dev", d).apply()
        return d
    }

    /** Çagyryş kody: TM-XXXXX (bot hem şol bir usulda hasaplaýar). */
    fun code(ctx: Context): String {
        val a = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
        val h = sha("tvref|" + dev(ctx))
        return "TM-" + (0 until 5).map { a[(h[it].toInt() and 0xff) % a.length] }.joinToString("")
    }

    // ---- şifrlemek (HMAC-SHA256 akymy + HMAC belgisi; bot Python-da şol bir usulda açýar) ----
    private fun hmac(k: ByteArray, d: ByteArray): ByteArray = Mac.getInstance("HmacSHA256").run { init(SecretKeySpec(k, "HmacSHA256")); doFinal(d) }

    fun enc(pt: String): String? = F?.let { encK(it, pt) }
    fun dec(s: String): String? = F?.let { decK(it, s) }

    /** Açar Drive faýlynyň kimliginden: sha256("tvmsg|fid") we sha256("tvmac|fid"). */
    fun encK(fid: String, pt: String, n: ByteArray = ByteArray(12).also { rnd.nextBytes(it) }): String {
        val ke = sha("tvmsg|$fid"); val km = sha("tvmac|$fid")
        val p = pt.toByteArray(Charsets.UTF_8)
        val c = xor(ke, n, p)
        val tag = hmac(km, n + c).copyOf(16)
        return "v1." + Base64.encodeToString(n + c + tag, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP)
    }

    fun decK(fid: String, s: String): String? {
        val ke = sha("tvmsg|$fid"); val km = sha("tvmac|$fid")
        if (!s.startsWith("v1.")) return null
        val b = runCatching { Base64.decode(s.substring(3), Base64.URL_SAFE or Base64.NO_PADDING) }.getOrNull() ?: return null
        if (b.size < 28) return null
        val n = b.copyOfRange(0, 12); val c = b.copyOfRange(12, b.size - 16); val tag = b.copyOfRange(b.size - 16, b.size)
        if (!MessageDigest.isEqual(hmac(km, n + c).copyOf(16), tag)) return null
        return String(xor(ke, n, c), Charsets.UTF_8)
    }

    private fun xor(k: ByteArray, n: ByteArray, d: ByteArray): ByteArray {
        val out = ByteArray(d.size); var i = 0; var ctr = 0
        while (i < d.size) {
            val ks = hmac(k, n + byteArrayOf((ctr ushr 24).toByte(), (ctr ushr 16).toByte(), (ctr ushr 8).toByte(), ctr.toByte()))
            for (j in ks.indices) { if (i >= d.size) break; out[i] = (d[i].toInt() xor ks[j].toInt()).toByte(); i++ }
            ctr++
        }
        return out
    }

    // ---- HTTP: birikende tunel içinden, ýogsa göni ----
    private fun open(url: String, viaTunnel: Boolean): HttpURLConnection {
        val port = State.socks
        val c = if (viaTunnel && port > 0) URL(url).openConnection(Proxy(Proxy.Type.HTTP, InetSocketAddress("127.0.0.1", port))) as HttpURLConnection
        else URL(url).openConnection() as HttpURLConnection
        c.connectTimeout = 8000; c.readTimeout = 12000
        return c
    }

    private fun tries(): List<Boolean> = if (State.now == State.ON && State.socks > 0) listOf(true, false) else listOf(false)

    private fun post(topic: String, body: String): Boolean {
        for (t in tries()) {
            val ok = runCatching {
                val c = open(host() + topic, t)
                c.requestMethod = "POST"; c.doOutput = true
                c.setRequestProperty("Content-Type", "text/plain; charset=utf-8")
                c.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
                val code = c.responseCode; c.disconnect(); code in 200..299
            }.getOrDefault(false)
            if (ok) return true
        }
        return false
    }

    /** Konudaky habarlar (since: habar kimligi ýa-da «12h»). */
    private fun poll(topic: String, since: String): List<JSONObject>? {
        for (t in tries()) {
            val r = runCatching {
                val c = open(host() + topic + "/json?poll=1&since=" + since, t)
                val txt = c.inputStream.use { it.readBytes() }.toString(Charsets.UTF_8); c.disconnect()
                txt.lineSequence().filter { it.isNotBlank() }.mapNotNull { runCatching { JSONObject(it) }.getOrNull() }
                    .filter { it.optString("event") == "message" }.toList()
            }.getOrNull()
            if (r != null) return r
        }
        return null
    }

    // ---- nobat ----
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("msg", 0)

    /** Bota habar goýýar (programmadan çykylsa-da ýitmeýär). */
    fun send(ctx: Context, o: JSONObject) {
        val c = ctx.applicationContext
        o.put("dev", dev(c)).put("ver", ver(c)).put("lang", Lang.cur).put("ts", System.currentTimeMillis() / 1000)
            .put("model", android.os.Build.MANUFACTURER + " " + android.os.Build.MODEL).put("code", code(c))
            .put("ack", prefs(c).getInt("seq", 0))
        if (o.optString("k") in setOf("tk", "ref", "gift", "human", "ka")) waitAt = System.currentTimeMillis()
        synchronized(this) {
            val q = JSONArray(prefs(c).getString("q", "[]"))
            q.put(o.toString())
            val keep = JSONArray(); val from = maxOf(0, q.length() - 60)
            for (i in from until q.length()) keep.put(q.get(i))
            prefs(c).edit().putString("q", keep.toString()).apply()
        }
        kick()
    }

    /** Global chat-a ýazmak (göni konuna). */
    fun gsend(ctx: Context, nick: String, text: String) {
        val o = JSONObject().put("i", dev(ctx)).put("n", nick.take(32)).put("t", text.take(600))
        Thread { val e = enc(o.toString()); val tp = topicG(); val ok = e != null && tp != null && post(tp, e)
            if (!ok) events.add(JSONObject().put("k", "gfail")) else { gAt = 0L; kick() } }.start()
    }

    fun ver(ctx: Context): String = runCatching { ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName }.getOrNull() ?: "0"

    // ---- işçi ----
    private val lock = Object()
    fun kick() { synchronized(lock) { lock.notifyAll() } }
    @Volatile private var gAt = 0L
    @Volatile private var inAt = 0L
    @Volatile private var waitAt = 0L        // soňky soragyň wagty: jogap garaşylýan wagty ýygy barlanýar

    fun start(ctx: Context) {
        app = ctx.applicationContext
        if (started) return
        started = true
        Thread({ loop() }, "msg").apply { isDaemon = true }.start()
    }

    private fun loop() {
        while (true) {
            val c = app ?: break
            runCatching { flush(c) }
            val now = System.currentTimeMillis()
            val on = State.now == State.ON
            // ntfy.sh bir IP-den az soraga rugsat berýär (köp adam bir VPN serweriniň IP-sinden çykýar), şonuň üçin seýrek:
            // jogap garaşylýan bolsa (soňky 40 min) ekranda 20 sn / fonda 3 min, ýogsa ekranda 2 min / fonda 10 min
            val waiting = now - waitAt < 40 * 60_000L
            val inEvery = if (visible) (if (waiting) 20_000L else 120_000L) else (if (waiting) 180_000L else 600_000L)
            if ((visible || on) && now - inAt > inEvery) { inAt = now; runCatching { inbox(c) } }
            val gEvery = if (watchG) 8_000L else 60_000L
            if (visible && now - gAt > gEvery) { gAt = now; runCatching { global() } }
            synchronized(lock) { runCatching { lock.wait(if (watchG) 2500L else 5000L) } }
        }
    }

    private fun flush(c: Context) {
        val tp = topicBot() ?: return
        while (true) {
            val first = synchronized(this) { JSONArray(prefs(c).getString("q", "[]")).let { if (it.length() == 0) null else it.getString(0) } } ?: return
            val e = enc(first) ?: return
            if (!post(tp, e)) return
            synchronized(this) {
                val q = JSONArray(prefs(c).getString("q", "[]")); val rest = JSONArray()
                for (i in 1 until q.length()) rest.put(q.get(i))
                prefs(c).edit().putString("q", rest.toString()).apply()
            }
        }
    }

    private fun inbox(c: Context) {
        val tp = topicMe(c) ?: return
        val p = prefs(c)
        val list = poll(tp, p.getString("inId", null) ?: "12h") ?: return
        var seq = p.getInt("seq", 0)
        for (m in list) {
            p.edit().putString("inId", m.optString("id")).apply()
            val o = dec(m.optString("message"))?.let { runCatching { JSONObject(it) }.getOrNull() } ?: continue
            val s = o.optInt("seq", 0)
            if (s in 1..seq) continue      // öň gelen habar (bot gaýtadan iberdi)
            if (s > 0) seq = s
            p.edit().putInt("seq", seq).apply()
            o.optString("key").takeIf { it.isNotEmpty() }?.let { k -> if (Lic.exp(c) == null) Lic.save(c, k) }   // sowgat / çagyryş açary
            pend(c, JSONObject().put("k", "in").put("m", o))
            if (!visible && o.optString("k") == "tk" && o.optString("who") == "a") Svc.notifyReply(c, o.optString("t"))
        }
    }

    /** Profil suraty: hemmeler görer (diňe öz serweri bolanda, ntfy.sh uly faýly kabul etmeýär). */
    fun photo(ctx: Context, data: String) {
        val tp = base?.let { it + "p" + dev(ctx) } ?: return
        if (Sub.relay.isEmpty()) return
        val o = JSONObject().put("ph", data.take(90_000)).put("v", System.currentTimeMillis() / 1000)
        Thread { val e = enc(o.toString()); if (e != null && !post(tp, e)) events.add(JSONObject().put("k", "phfail")) }.start()
    }

    /** Başga adamyň suraty. */
    fun getPhoto(dev: String) {
        if (!Regex("^[0-9a-f]{12}$").matches(dev) || Sub.relay.isEmpty()) return
        val tp = base?.let { it + "p" + dev } ?: return
        Thread {
            val m = poll(tp, "all")?.lastOrNull() ?: return@Thread
            val o = dec(m.optString("message"))?.let { runCatching { JSONObject(it) }.getOrNull() } ?: return@Thread
            events.add(JSONObject().put("k", "ph").put("dev", dev).put("d", o.optString("ph")).put("v", o.optLong("v")))
        }.start()
    }

    /** Barlag: habar serweri tunelden we göni açylýarmy. */
    fun diag(): JSONObject {
        val u = host() + "health"
        fun t(via: Boolean) = runCatching { val c = open(u, via); val code = c.responseCode; c.disconnect(); code }.getOrElse { -1 }
        return JSONObject().put("relay", Sub.relay.isNotEmpty()).put("tun", if (State.now == State.ON && State.socks > 0) t(true) else 0).put("direct", t(false))
    }

    /** Gelen habar ekran alýança telefonda saklanýar (programma ýapylsa-da ýitmez). */
    private fun pend(c: Context, o: JSONObject) = synchronized(this) {
        val q = JSONArray(prefs(c).getString("pend", "[]")); q.put(o)
        val keep = JSONArray(); for (i in maxOf(0, q.length() - 100) until q.length()) keep.put(q.get(i))
        prefs(c).edit().putString("pend", keep.toString()).apply()
    }

    /** Ekran üçin ähli täze wakalar. */
    fun take(c: Context): JSONArray = synchronized(this) {
        val out = JSONArray(prefs(c).getString("pend", "[]"))
        prefs(c).edit().putString("pend", "[]").apply()
        while (true) { val e = events.poll() ?: break; out.put(e) }
        out
    }

    private fun global() {
        val tp = topicG() ?: return
        val list = poll(tp, "12h") ?: return
        val arr = JSONArray(); val del = JSONArray()
        for (m in list) {
            val o = dec(m.optString("message"))?.let { runCatching { JSONObject(it) }.getOrNull() } ?: continue
            if (o.has("del")) { del.put(o.optString("del")); continue }
            arr.put(JSONObject().put("id", m.optString("id")).put("time", m.optLong("time")).put("i", o.optString("i"))
                .put("n", o.optString("n")).put("t", o.optString("t")))
        }
        events.add(JSONObject().put("k", "g").put("list", arr).put("del", del))
    }
}
