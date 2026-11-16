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
    @Volatile var dmPage = false            // hususy habarlar sanawy açyk
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
    fun code(ctx: Context): String = codeOf(dev(ctx))
    /** Islendik telefonyň kody (eýesi başga ulanyjynyň ID-sini görýär). */
    fun codeOf(d: String): String {
        val a = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
        val h = sha("tvref|" + d)
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

    // ---- 1.40: öz VPS (relay) — VPN-siz açylýan bolsa esasy ýol (okalyş çägi ýok); jogap bermese 2 minut Firestore ----
    @Volatile private var relBadUntil = 0L
    fun relOn() = Sub.relay.isNotEmpty() && System.currentTimeMillis() > relBadUntil
    private fun relFail() { relBadUntil = System.currentTimeMillis() + 120_000L; subDue = true }
    // 1.41: abuna faýly (VPS salgysy, baza) — bot üýtgedende programma köne salgyda galmasyn: ekranda 5 minutda bir, VPS jogap bermese 1 minutda
    @Volatile private var subDue = false
    @Volatile private var subTry = 0L
    private fun subCheck(c: Context, now: Long) {
        if (!visible || now - subTry < 60_000L || !(subDue || now - Sub.okAt > 300_000L)) return
        subTry = now; subDue = false
        Thread { runCatching { if (Sub.refresh(c, 8000)) events.add(JSONObject().put("k", "srv")) } }.apply { isDaemon = true }.start()
    }
    /** VPS üýtgese köne kursory (r123 — başga serweriň belgisi) taşla. */
    private fun relCur(c: Context) {
        val p = prefs(c)
        if (p.getString("relHost", "") != Sub.relay) { p.edit().putString("relHost", Sub.relay).remove("inId").apply(); gRelId = null }
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
    private fun poll(topic: String, since: String, wait: Int = 0): List<JSONObject>? {
        for (t in tries()) {
            val r = runCatching {
                val c = open(host() + topic + "/json?poll=1&since=" + since + (if (wait > 0) "&wait=$wait" else ""), t)
                if (wait > 0) c.readTimeout = (wait + 15) * 1000   // 1.40.1: VPS täze habar gelýänçä garaşýar
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
        if (o.optString("k") in setOf("tk", "ref", "gift", "human", "ka", "adm", "buy", "payq", "vote", "lvlq", "kgift", "lvof")) waitAt = System.currentTimeMillis()
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
        Thread { val ok = gPut(o)
            if (!ok) events.add(JSONObject().put("k", "gfail")) else { gAt = 0L; kick() } }.start()
    }

    /** 1.40: Global chat setiri — VPS-e (kimligi bilen) we Firestore-a (köne wersiýalar görsün; «rl» — bot VPS-e gaýtadan goýmasyn).
     *  Kimlik ikisinde-de birmeňzeş, şonuň üçin jogap / tepki / pozmak hemme ýerde işleýär. Iş akymynda (Thread) çagyrylýar. */
    fun gPut(o: JSONObject): Boolean {
        val id = Fs.newId(); val tp = topicG()
        var rel = false
        if (relOn() && tp != null) { rel = enc(JSONObject(o.toString()).put("id", id).toString())?.let { post(tp, it) } ?: false; if (!rel) relFail() }
        val fs = Fs.on() && (enc((if (rel) JSONObject(o.toString()).put("rl", 1) else o).toString())?.let { Fs.write("g/$id", it) } ?: false)
        if (!rel && !fs && !Fs.on() && tp != null) return enc(o.toString())?.let { post(tp, it) } ?: false   // köne ýol (Firestore ýok)
        return rel || fs
    }

    fun ver(ctx: Context): String = runCatching { ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName }.getOrNull() ?: "0"

    // ---- işçi ----
    private val lock = Object()
    /** 1.38.2: hemme zat VPN-li hem VPN-siz Firestore arkaly (eýesiniň islegi). Öz relay (VPS) diňe ätiýaçlyk:
     *  Firestore jogap bermese (meselem gündelik çäk dolsa) — VPN bagly bolsa relay arkaly işlemegini dowam edýär. */

    fun kick() { synchronized(lock) { lock.notifyAll() } }
    /** Global chat-a ýazylandan soň derrew täzeden oka (habar gijä galmasyn). */
    fun gNow() { gAt = 0L; kick() }
    @Volatile private var gAt = 0L
    @Volatile private var newsAt = 0L

    /** Habarlar Firestore-dan (bot n/list ýazýar): admin iberen badyna gelýär. */
    private fun newsFs() {
        val o = Fs.get("n/list")?.first?.let { dec(it) }?.let { runCatching { JSONObject(it) }.getOrNull() } ?: return
        val a = o.optJSONArray("news") ?: return
        val l = ArrayList<Triple<String, Long, String>>()
        for (i in 0 until a.length()) {
            val n = a.optJSONObject(i) ?: continue
            val j = JSONObject().put("t", n.optString("t")).put("x", n.optString("x"))
            n.optString("img").takeIf { it.isNotEmpty() }?.let { j.put("img", it) }
            n.optJSONArray("btn")?.let { j.put("btn", it) }
            l.add(Triple(n.optString("id"), n.optLong("ts"), j.toString()))
        }
        val changed = l.map { it.first } != Sub.news.map { it.first }
        Sub.newsFs = l; Sub.news = l
        if (changed) events.add(JSONObject().put("k", "srv"))
    }
    @Volatile private var inAt = 0L
    @Volatile private var inPend = false
    /** 1.38: FCM bildirişi — botdan täze habar: gelen gutyny şol bada barla (programma fonda bolsa-da bir gezek). */
    fun pushIn() { inAt = 0L; inPend = true; kick() }
    @Volatile private var waitAt = 0L        // soňky soragyň wagty: jogap garaşylýan wagty ýygy barlanýar

    fun start(ctx: Context) {
        app = ctx.applicationContext
        if (started) return
        started = true
        Thread({ loop() }, "msg").apply { isDaemon = true }.start()
        Thread({ relInLoop() }, "relin").apply { isDaemon = true }.start()
        Thread({ relGLoop() }, "relg").apply { isDaemon = true }.start()
    }

    private fun loop() {
        while (true) {
            val c = app ?: break
            runCatching { flush(c) }
            val now = System.currentTimeMillis()
            subCheck(c, now)
            val on = State.now == State.ON
            // ntfy.sh bir IP-den az soraga rugsat berýär (köp adam bir VPN serweriniň IP-sinden çykýar), şonuň üçin seýrek:
            // jogap garaşylýan bolsa (soňky 40 min) ekranda 20 sn / fonda 3 min, ýogsa ekranda 2 min / fonda 10 min
            val waiting = now - waitAt < 40 * 60_000L
            // Firestore: jogap garaşylanda ekranda ilkinji 3 minut 4 sn-da bir, soň 20 sn (her boş sorag hem 1 okalyş)
            val hot = now - waitAt < 3 * 60_000L
            val fast = Sub.fast && Fs.on()   // 1.34: çalt rejim — eýesi Firestore tölegini açdy
            val push = Push.ok() && Fs.on() && !fast   // 1.38: bildiriş (FCM) işleýär — bot özi habar berýär, barlag diňe ätiýaçlyk
            val rel = relOn()   // 1.40: VPS-de okalyş tölegsiz — ýygy barlap bolýar
            val inEvery = if (fast) (if (visible) (if (hot) 1_500L else 5_000L) else 30_000L)
                else if (rel) (if (visible) (if (hot) 3_000L else if (waiting) 10_000L else 20_000L) else (if (waiting) 60_000L else 300_000L))
                else if (push) (if (visible) (if (hot) 20_000L else 300_000L) else 1_800_000L)
                else if (Fs.on() || Sub.relay.isNotEmpty()) (if (visible) (if (hot) 4_000L else if (waiting) 20_000L else 60_000L) else (if (waiting) 60_000L else 300_000L))
                else if (visible) (if (waiting) 20_000L else 120_000L) else (if (waiting) 180_000L else 600_000L)
            val adm = admPw(c) != null && Fs.on()   // admin: fonda hem bilet bildirişleri (2 minutda bir)
            val ip = inPend; inPend = false
            if (!rel && (ip || ((visible || on || adm || fast) && now - inAt > (if (adm && !visible && !push) minOf(inEvery, 120_000L) else inEvery)))) { inAt = now; runCatching { inbox(c) } }   // 1.40.1: VPS — relInLoop
            // 1.39.1: chat açyk, ýöne soňky 2 minutda täze habar ýok bolsa 12 sn-da bir (her boş sorag hem 1 okalyş)
            val gEvery = if (watchG) (if (fast) 1_500L else if (rel) 3_000L else if (Fs.on()) (if (now - gNewAt < 120_000L) 5_000L else 12_000L) else 8_000L) else if (fast) 20_000L else if (rel) 30_000L else if (push) 300_000L else 120_000L
            if (visible && !(rel && watchG) && now - gAt > gEvery) { gAt = now; runCatching { global() } }   // 1.40.1: chat açyk + VPS — relGLoop
            runCatching { Chat.poll(c, visible, dmPage) }
            if (visible || on) runCatching { State.pingExtra(c) }
            if (visible && Fs.on() && now - newsAt > (if (fast) 60_000L else 120_000L)) { newsAt = now; runCatching { newsFs() } }
            synchronized(lock) { runCatching { lock.wait(if (fast && visible) 700L else if (watchG || Chat.watch != null || (hot && visible)) 2000L else 5000L) } }
        }
    }

    private fun flush(c: Context) {
        val tp = topicBot() ?: return
        while (true) {
            val first = synchronized(this) { JSONArray(prefs(c).getString("q", "[]")).let { if (it.length() == 0) null else it.getString(0) } } ?: return
            val e = enc(first) ?: return
            // 1.40: VPS açylsa ilki VPS (bot ony 3 sn-da bir okaýar, Firestore çägine degmeýär), bolmasa Firestore
            val sent = if (relOn()) (post(tp, e).also { if (!it) relFail() } || (Fs.on() && Fs.write("m/" + Fs.newId(), e)))
                else (Fs.on() && Fs.write("m/" + Fs.newId(), e)) || ((!Fs.on() || Sub.relay.isNotEmpty()) && post(tp, e))   // Firestore ýalňyş — relay ätiýaçlyk
            if (!sent) return
            synchronized(this) {
                val q = JSONArray(prefs(c).getString("q", "[]")); val rest = JSONArray()
                for (i in 1 until q.length()) rest.put(q.get(i))
                prefs(c).edit().putString("q", rest.toString()).apply()
            }
        }
    }

    private val inLock = Object()
    private fun inbox(c: Context, wait: Int = 0) = synchronized(inLock) { inbox0(c, wait) }
    private fun inbox0(c: Context, wait: Int) {
        val p = prefs(c); relCur(c)
        val tp = topicMe(c)
        var useFs = false
        // 1.40: VPS açylsa ilki VPS (okalyş çägi ýok); bolmasa Firestore (VPN-siz): d/<telefon>/i — diňe täzeleri (t > soňky)
        val triedRel = relOn() && tp != null
        var list: List<Pair<String, String>>? = if (triedRel) poll(tp!!, p.getString("inId", null) ?: "12h", if (p.getString("inId", null) != null) wait else 0)?.map { it.optString("id") to it.optString("message") } else null
        if (triedRel && list == null) relFail()
        if (list == null) {
            val fsGot = if (Fs.on()) Fs.query("d/" + dev(c), "i", p.getString("fsIn", null), 50) else null
            if (fsGot != null) { useFs = true; list = fsGot.map { (_, b, t) -> t to b } }
            else {   // Firestore ýok / jogap bermedi — relay (VPN bagly bolsa açylýar)
                if ((Fs.on() && Sub.relay.isEmpty()) || tp == null || triedRel) return
                list = (poll(tp, p.getString("inId", null) ?: "12h") ?: return).map { it.optString("id") to it.optString("message") }
            }
        }
        var seq = p.getInt("seq", 0)
        for ((id, body) in list) {
            p.edit().putString(if (useFs) "fsIn" else "inId", id).apply()
            val o = dec(body)?.let { runCatching { JSONObject(it) }.getOrNull() } ?: continue
            if (o.optString("k") == "adm") { admIn(c, o); continue }
            val s = o.optInt("seq", 0)
            if (s in 1..seq) continue      // öň gelen habar (bot gaýtadan iberdi)
            if (s > 0) seq = s
            p.edit().putInt("seq", seq).apply()
            o.optString("key").takeIf { it.isNotEmpty() }?.let { k -> if (Lic.exp(c) == null || o.optString("k") == "buy" || o.optString("k") == "lvl" || o.optString("k") == "prem") Lic.save(c, k) }   // sowgat / çagyryş / satyn alnan açar / 1.43: Premium
            if (o.optString("k") == "prem") subDue = true   // 1.43: täze açar abuna faýlynda — derrew täzele
            if (o.optString("k") == "uban") Lic.setBanned(c, o.optBoolean("on"))
            pend(c, JSONObject().put("k", "in").put("m", o))
            if (!visible && o.optString("k") == "tk" && o.optString("who") == "a") Svc.notifyReply(c, o.optString("t"))
            if (!visible && o.optString("k") == "atk" && admPw(c) != null) Svc.notifyAdmin(c, o.optInt("tid"), o.optString("n"), o.optString("t"))
        }
    }

    // ---- admin paneli: haýyş açar söz bilen şifrlenýär (bot hem şeýle açýar), jogap hem şol açar bilen ----
    fun admNorm(pw: String) = pw.replace(Regex("\\s+"), "").uppercase()
    fun admId(pw: String) = hex(sha("tvaid|" + admNorm(pw))).take(16)
    fun admPw(c: Context): String? = prefs(c).getString("apw", null)
    fun admMe(c: Context): JSONObject? = prefs(c).getString("admMe", null)?.let { runCatching { JSONObject(it) }.getOrNull() }

    /** a: {"a": "login", "pw": …} ýa-da {"a": "get" / "reply" / …}. */
    fun adm(ctx: Context, a: JSONObject) {
        val c = ctx.applicationContext; val p = prefs(c)
        val act = a.optString("a")
        if (act == "login") {
            val pw = admNorm(a.optString("pw")); a.remove("pw")
            if (pw.length < 6) return
            p.edit().putString("apw", pw).remove("admMe").putBoolean("admLogin", true).apply()
        }
        val pw = admPw(c) ?: return
        val ts = maxOf(System.currentTimeMillis(), p.getLong("admTs", 0) + 1)
        p.edit().putLong("admTs", ts).apply()
        a.put("ts", ts)
        send(c, JSONObject().put("k", "adm").put("aid", admId(pw)).put("x", encK("adm|$pw", a.toString())))
        if (act == "logout") p.edit().remove("apw").remove("admMe").apply()
    }

    /** Şifrsiz ýalňyşlyk («açar söz nädogry», «gulp») diňe giriş garaşylýan wagty kabul edilýär — başga biri admini çykaryp bilmesin. */
    internal fun admIn(c: Context, o: JSONObject) {
        val p = prefs(c)
        val j: JSONObject
        if (o.has("x")) {
            val pw = admPw(c) ?: return
            j = decK("adm|$pw", o.optString("x"))?.let { runCatching { JSONObject(it) }.getOrNull() } ?: return
        } else {
            if (!p.getBoolean("admLogin", false)) return
            j = o
        }
        p.edit().putBoolean("admLogin", false).apply()
        val err = j.optString("err")
        if (err.isNotEmpty()) {
            p.edit().remove("apw").remove("admMe").apply()
            events.add(JSONObject().put("k", "adm").put("err", err).put("s", j.optInt("s")))
            return
        }
        j.optJSONObject("me")?.let { p.edit().putString("admMe", it.toString()).apply() }
        events.add(JSONObject().put("k", "adm").put("d", j))
    }

    /** Profil suraty: hemmeler görer (diňe öz serweri bolanda, ntfy.sh uly faýly kabul etmeýär). */
    fun photo(ctx: Context, data: String) {
        val tp = base?.let { it + "p" + dev(ctx) } ?: return
        if (Sub.relay.isEmpty() && !Fs.on()) return
        val o = JSONObject().put("ph", data.take(90_000)).put("v", System.currentTimeMillis() / 1000)
        val d = dev(ctx)
        Thread { val e = enc(o.toString()); if (e == null || !(if (Fs.on()) Fs.write("p/$d", e, create = false) else post(tp, e))) events.add(JSONObject().put("k", "phfail")) }.start()
    }

    /** Başga adamyň suraty. */
    fun getPhoto(dev: String) {
        if (!Regex("^[0-9a-f]{12}$").matches(dev) || (Sub.relay.isEmpty() && !Fs.on())) return
        val tp = base?.let { it + "p" + dev } ?: return
        Thread {
            val body = if (Fs.on()) Fs.get("p/$dev")?.first else poll(tp, "all")?.lastOrNull()?.optString("message")
            val o = body?.let { dec(it) }?.let { runCatching { JSONObject(it) }.getOrNull() } ?: return@Thread
            events.add(JSONObject().put("k", "ph").put("dev", dev).put("d", o.optString("ph")).put("v", o.optLong("v")))
        }.start()
    }

    /** Barlag: habar serweri tunelden we göni açylýarmy. */
    fun diag(): JSONObject {
        val u = host() + "health"
        fun t(via: Boolean) = runCatching { val c = open(u, via); val code = c.responseCode; c.disconnect(); code }.getOrElse { -1 }
        if (Fs.on() && Sub.relay.isEmpty()) return JSONObject().put("fs", Fs.ping())   // 1.40.2: VPS bar bolsa VPS barlanýar (esasy ýol)
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

    // Firestore Global chat: ilki soňky 150, soň diňe täzeler (okalyş az bolsun). 1.32.1: doly täzelemek diňe chat açyk wagty 15 minutda bir
    // (öň her 3 minutda 150 okalyş — programma açyk durka hemme sahypada; Firestore-yň mugt gündelik çägi doldy)
    // 1.39.1: soňky setirler telefonda saklanýar — programma her açylanda 150 okalyş däl, diňe täzeler (mugt gündelik çäk dolýardy);
    // doly täzelemek (bot pozan habarlar üçin) chat açyk wagty 60 minutda bir
    private val gfs = ArrayList<JSONObject>(); @Volatile private var gfsT: String? = null; @Volatile private var gfsFull = 0L
    @Volatile private var gfsLoaded = false; @Volatile var gNewAt = 0L

    private fun gfsFile(): java.io.File? = app?.filesDir?.let { java.io.File(it, "gfs.json") }

    private fun gfsLoad() {
        if (gfsLoaded) return; gfsLoaded = true
        runCatching {
            val o = JSONObject(gfsFile()?.takeIf { it.exists() }?.readText() ?: return)
            val a = o.getJSONArray("l"); for (i in 0 until a.length()) gfs.add(a.getJSONObject(i))
            gfsT = o.optString("t").ifEmpty { null }; gfsFull = o.optLong("full")
            if (o.optString("rh") == Sub.relay) gRelId = o.optString("r").ifEmpty { null }
        }.onFailure { gfs.clear(); gfsT = null; gfsFull = 0L }
    }

    private fun gfsSave() = runCatching {
        val a = JSONArray(); gfs.takeLast(GMAX).forEach { a.put(it) }
        gfsFile()?.writeText(JSONObject().put("t", gfsT ?: "").put("full", gfsFull).put("r", gRelId ?: "").put("rh", Sub.relay).put("at", System.currentTimeMillis()).put("l", a).toString())
    }

    private fun globalFs() {
        gfsLoad()
        val now = System.currentTimeMillis()
        val full = gfsT == null || (!Fs.vps() && watchG && now - gfsFull > (if (Sub.fast) 180_000 else 3_600_000))   // 1.43.5: VPS-de çäk ýok — doly täzelemek gerek däl
        val got = (if (full) Fs.query("", "g", null, 150, desc = true)?.reversed() else Fs.query("", "g", gfsT, 80)) ?: return   // tepkiler hem setir bolup gelýär
        if (full) { if (!Fs.vps()) gfs.clear(); gfsFull = now }   // 1.43.5: VPS-de arassalanmaýar — öňki habarlar ýitmesin
        val ids = gfs.mapTo(HashSet()) { it.optString("id") }
        for ((id, b, t) in got) {
            gfsT = t
            val o = dec(b)?.let { runCatching { JSONObject(it) }.getOrNull() } ?: continue
            if (!ids.add(id)) continue   // eýýäm bar (VPS-den geldi)
            gfs.add(gRow(id, Fs.sec(t), o))
        }
        gfs.sortBy { it.optLong("time") }
        while (gfs.size > GMAX) gfs.removeAt(0)
        if (got.isNotEmpty()) { if (!full) gNewAt = now; gfsSave() }
        if (!full && got.size >= 80) gAt = 0L   // köp täze setir galdy (programma uzak ýapyk durdy) — derrew dowamy
        events.add(JSONObject().put("k", "g").put("list", JSONArray(gfs.toList())).put("del", JSONArray()))
    }

    private fun gRow(id: String, time: Long, o: JSONObject): JSONObject = JSONObject().put("id", id).put("time", time).put("i", o.optString("i")).put("n", o.optString("n")).put("t", o.optString("t"))
        .put("st", o.optString("st").take(16)).put("pi", o.optString("pi").take(40)).put("vc", o.optString("vc").take(700)).put("vs", o.optInt("vs")).put("rp", o.optJSONObject("rp")?.let { Chat.rp(it) } ?: JSONObject.NULL)
        .put("re", o.optString("re").take(40)).put("e", o.optString("e").take(8)).put("off", o.optBoolean("off")).put("lv", o.optInt("lv").coerceIn(0, 10)).put("ow", if (o.has("ow")) o.optInt("ow") else -1)
        .put("dl", o.optString("dl").take(40)).put("ed", o.optString("ed").take(40)).put("sty", o.optInt("sty"))

    /** 1.40: Global chat VPS-den (soňky kursordan täzeler; köne wersiýalaryň Firestore habarlaryny bot VPS-e geçirýär).
     *  «del» — bot pozan habar. Dönüş: false — VPS jogap bermedi (Firestore-a geç). */
    @Volatile private var gRelId: String? = null
    private const val GMAX = 800   // 1.43.5: Global chat-da telefonda saklanýan setirler (öň 400 / 200)
    private val gLock = Object()
    private fun globalRel(wait: Int = 0): Boolean {
        synchronized(gLock) { gfsLoad(); app?.let { relCur(it) } }
        val tp = topicG() ?: return false
        val cur = gRelId
        val got = poll(tp, cur ?: "7d", if (cur != null) wait else 0) ?: run { relFail(); return false }   // 1.43.5: ilkinji gezek soňky 7 gün
        synchronized(gLock) { return globalRel2(got) }
    }
    private fun globalRel2(got: List<JSONObject>): Boolean {
        val now = System.currentTimeMillis()
        val ids = gfs.mapTo(HashSet()) { it.optString("id") }
        val del = JSONArray(); var added = false
        for (m in got) {
            gRelId = m.optString("id")
            val o = dec(m.optString("message"))?.let { runCatching { JSONObject(it) }.getOrNull() } ?: continue
            if (o.has("del")) { val d = o.optString("del"); del.put(d); gfs.removeAll { it.optString("id") == d }; continue }
            val id = o.optString("id").ifEmpty { m.optString("id") }
            if (!ids.add(id)) continue
            gfs.add(gRow(id, o.optLong("ts").takeIf { it > 0 } ?: m.optLong("time"), o)); added = true
        }
        if (added) { gfs.sortBy { it.optLong("time") }; while (gfs.size > GMAX) gfs.removeAt(0); gNewAt = now }
        if (got.isNotEmpty()) gfsSave()
        events.add(JSONObject().put("k", "g").put("list", JSONArray(gfs.toList())).put("del", del))
        return true
    }

    /** 1.40.1: VPS — garaşýan soraglar: täze habar gelen badyna (gijikme ýok). Ýalňyşlykda relFail → köne ýol (Firestore). */
    private fun relInLoop() {
        while (true) {
            val c = app
            val on = State.now == State.ON
            if (c == null || !relOn() || !(visible || on || admPw(c) != null)) { runCatching { Thread.sleep(2000) }; continue }
            val t0 = System.currentTimeMillis()
            runCatching { inbox(c, 25) }
            if (System.currentTimeMillis() - t0 < 500) runCatching { Thread.sleep(1000) }   // ýalňyşlyk / köne serwer — aýlaw gyzmasyn
        }
    }

    private fun relGLoop() {
        while (true) {
            if (!(relOn() && visible && watchG)) { runCatching { Thread.sleep(700) }; continue }
            val t0 = System.currentTimeMillis()
            runCatching { globalRel(25) }
            if (System.currentTimeMillis() - t0 < 300) runCatching { Thread.sleep(500) }
        }
    }

    private fun global() {
        if (relOn() && globalRel()) return
        synchronized(gLock) { if (Fs.on()) { globalFs(); return } }
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
