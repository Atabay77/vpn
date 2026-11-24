package tm.yol.vpn

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

object N {
    init { System.loadLibrary("yolsec") }
    @JvmStatic external fun u(): String
    /** 1.47.16: #tvy sanawyny açýar — açar programmanyň gol şahadatnamasyna bagly (mod açyp bilmeýär). */
    @JvmStatic external fun d(ctx: Context?, salt: String, mask: String, blob: String): ByteArray?
    /** 1.47.16: gorag ýagdaýy ("faýl8.pm8.flags") — bot modlary tanamak üçin. */
    @JvmStatic external fun s(ctx: Context?): String
}

/** Abonelikteki bir sunucu. uri yalnız bellekte ve şifreli önbellekte durur, ekranda gösterilmez. */
data class Server(val flag: String, val country: String, val title: String, val proto: String, val uri: String,
                  val game: Boolean = false, val ru: Boolean = false) {
    /** Seçimi hatırlamak için: abonelik karışsa da aynı sunucu aynı kalır. */
    val key get() = flag + "|" + runCatching { Cfg.link(uri).let { "${it.host}:${it.port}" } }.getOrDefault(title)
    /** 1.43: «host:port» — mugt serwerleriň sanawy (#tvfree) bilen deňeşdirilýär. */
    val hp get() = runCatching { Cfg.link(uri).let { "${it.host}:${it.port}" } }.getOrDefault("")
}

object Sub {
    @Volatile var list: List<Server> = emptyList()
    /** 1.47.13: bagly serwer täze sanawda ýok bolsa-da (bot aýyrdy) birikme gutarýança sanawda galýar — ekranda başga serwer görünmesin. */
    private fun keepActive(l: List<Server>): List<Server> {
        val a = State.active ?: return l
        return if ((State.now == State.ON || State.now == State.WAIT) && l.none { it.key == a.key }) l + a else l
    }
    @Volatile var keys: Map<String, Long> = emptyMap()                 // key özeti → bitiş (sn, 0 = süresiz)
    @Volatile var upd: Map<String, Pair<String, String>> = emptyMap()  // "64"/"32"/"all" → (sürüm, Drive dosyası)
    @Volatile var ad: Pair<String, String>? = null                     // reklam: (resim Drive dosyası, link)
    @Volatile var okAt = 0L                                            // son başarılı güncelleme
    @Volatile var kdev: Map<String, String> = emptyMap()               // key özeti → baglanan telefon(lar), otur bilen
    @Volatile var newsFs: List<Triple<String, Long, String>>? = null   // Firestore-dan (n/list) — täzeräk, abuna faýlyndakydan öň
    @Volatile var osel = false   // 1.47.30: eýesi hem Premium satyjy (#tvosel)
    @Volatile var site = "https://turkmenvpn.ru"   // 1.47.27: täze wersiýa ýüklenýän sahypa (#tvsite — bloklansa bot çalşýar)
    @Volatile var ubans: Set<String> = emptySet()                      // doly gadagan edilenler (diňe VPN, 20 min)
    @Volatile var pin = ""   // 1.46.4: Global chatda berkidilen habar (JSON: id, n, t)
    @Volatile var roles: Map<String, Pair<String, String>> = emptyMap()   // telefon → (o = owner / a = admin, nik)
    @Volatile var kn: Map<String, Int> = emptyMap()                    // key özeti → näçe telefon ulanyp biler (1.16)
    @Volatile var news: List<Triple<String, Long, String>> = emptyList() // (kimlik, wagt, JSON {t,x}) — botdan habarlar
    @Volatile var online = 0                                            // häzir VPN-de näçe adam (bot hasaplaýar)
    @Volatile var fcmApp = ""                                           // 1.38: FCM programma kimligi (#tvfcm:)
    @Volatile var fast = false                                          // 1.34: çalt rejim (Firestore tölegli): hemme zat Firestore-da, ýygy barlag
    @Volatile var sess = 60                                             // 1.32: mugt birikme wagty, minut (0 = wagtsyz) — eýesi admin panelinden
    @Volatile var ai = false                                            // botda AI kömekçi açyk
    @Volatile var bans: Set<String> = emptySet()                        // Global chat-da gadagan edilen telefonlar
    @Volatile var relay = ""                                            // öz habar serweri (VPS); boş bolsa ntfy.sh
    @Volatile var fsProj = ""; @Volatile var fsKey = ""; @Volatile var fsDb = "(default)"                 // Google Firestore (VPN-siz açylýar)
    @Volatile var fsBase = ""                                           // 1.41: Firestore ýerine öz VPS (#tvdb) — Google ulanylmaýar
    @Volatile var free: Set<String> = emptySet()
    @Volatile var both: Set<String> = emptySet()                        // 1.47.2: kanal kodlary (#tvboth) — mugt hem bolsa Premium-da hem görünýär
    @Volatile var pkeys: Set<String>? = null                            // 1.43.4: Premium açarlar (#tvkp); null — köne bot (hemme açar Premium)                        // 1.43: mugt serwerler (host:port); boş bolsa — hemmesi mugt (köne bot)

    private fun body(text: String) = text.trim().let { t ->
        if (t.contains("://") || t.startsWith("#")) t else runCatching {
            String(android.util.Base64.decode(t, android.util.Base64.DEFAULT), Charsets.UTF_8)
        }.getOrDefault(t)
    }

    /** Botun yazdığı gizli satırlar: «#tvk: özet bitiş» ve «#tvu64: sürüm dosya». */
    fun meta(text: String) {
        val k = HashMap<String, Long>(); val u = HashMap<String, Pair<String, String>>(); var a: Pair<String, String>? = null
        val kd = HashMap<String, String>(); val kn2 = HashMap<String, Int>(); val rl = HashMap<String, Pair<String, String>>(); val ub = HashSet<String>(); val nw = ArrayList<Triple<String, Long, String>>(); var on = 0; var se = 60; var fa = false; var fc = ""; var aiOn = false; val bn = HashSet<String>(); var rel = ""; var fp = ""; var fk = ""; var fd = "(default)"; var fb = ""; val fr = HashSet<String>(); val bo = HashSet<String>(); var pk: HashSet<String>? = null; var pn = ""
        var os2 = false
        for (l in body(text).lineSequence()) {
            val p = l.trim().split(Regex("\\s+"))
            if (p.size >= 3 && p[0] == "#tvk:") p[2].toLongOrNull()?.let { k[p[1]] = it; if (p.size >= 4 && p[3] != "-") kd[p[1]] = p[3]; if (p.size >= 5) p[4].toIntOrNull()?.let { n -> kn2[p[1]] = n } }
            if (p.size >= 4 && p[0] == "#tvn:") runCatching {
                nw.add(Triple(p[1], p[2].toLong(), String(android.util.Base64.decode(p[3], android.util.Base64.URL_SAFE or android.util.Base64.NO_PADDING), Charsets.UTF_8)))
            }
            if (p.size >= 2 && p[0] == "#tvkp:") pk = HashSet(p[1].split(',').filter { it.length >= 8 })
            if (p.size >= 2 && p[0] == "#tvosel:") os2 = p[1] == "1"
            if (p.size >= 2 && p[0] == "#tvsite:" && Regex("^https?://[\\w.\\-]+(:\\d+)?(/[\\w./\\-]*)?$").matches(p[1])) site = p[1]   // 1.47.27: ýükleme sahypasy (botdan)
            if (p.size >= 2 && p[0] == "#tvboth:") bo.addAll(p[1].split(',').map { it.trim() }.filter { it.contains(':') })
            if (p.size >= 2 && p[0] == "#tvfree:") fr.addAll(p[1].split(',').map { it.trim() }.filter { it.contains(':') })
            if (p.size >= 3 && p[0] == "#tvrole:" && Regex("^[0-9a-f]{12}$").matches(p[1]) && p[2] in setOf("o", "a", "s"))   // 1.43: s — Premium satyjy
                rl[p[1]] = p[2] to runCatching { String(android.util.Base64.decode(p.getOrElse(3) { "" }, android.util.Base64.URL_SAFE or android.util.Base64.NO_PADDING), Charsets.UTF_8).take(32) }.getOrDefault("")
            if (p.size >= 2 && p[0] == "#tvpin:") pn = runCatching { String(android.util.Base64.decode(p[1], android.util.Base64.URL_SAFE or android.util.Base64.NO_PADDING), Charsets.UTF_8) }.getOrDefault("")   // 1.46.4: chatda berkidilen habar
            if (p.size >= 2 && p[0] == "#tvuban:") ub.addAll(p[1].split(',').filter { it.isNotBlank() })
            if (p.size >= 2 && p[0] == "#tvon:") on = p[1].toIntOrNull() ?: 0
            if (p.size >= 2 && p[0] == "#tvai:") aiOn = p[1] == "1"
            if (p.size >= 2 && p[0] == "#tvfast:") fa = p[1] == "1"
            if (p.size >= 2 && p[0] == "#tvfcm:" && Regex("^1:\\d{6,20}:android:[0-9a-f]{8,40}$").matches(p[1])) fc = p[1]
            if (p.size >= 2 && p[0] == "#tvsess:") p[1].toIntOrNull()?.let { if (it == 0 || it in 15..1440) se = it }
            if (p.size >= 2 && p[0] == "#tvban:") bn.addAll(p[1].split(',').filter { it.isNotBlank() })
            if (p.size >= 3 && p[0] == "#tvfs:" && Regex("^[a-z0-9\\-]{4,40}$").matches(p[1]) && Regex("^AIza[\\w\\-]{30,}$").matches(p[2])) { fp = p[1]; fk = p[2]; if (p.size >= 4 && Regex("^[a-z0-9\\-()]{1,63}$").matches(p[3])) fd = p[3] }
            if (p.size >= 2 && p[0] == "#tvrel:" && Regex("^https?://[\\w.:\\-]+/?$").matches(p[1])) rel = p[1].trimEnd('/')
            if (p.size >= 2 && p[0] == "#tvdb:" && Regex("^https?://[\\w.:\\-]+/?$").matches(p[1])) fb = p[1].trimEnd('/')
            if (p.size >= 3 && p[0].startsWith("#tvu") && p[0].endsWith(":")) u[p[0].removePrefix("#tvu").removeSuffix(":")] = p[1] to p[2]
            if (p.size >= 2 && p[0] == "#tvad:") a = p[1] to Cfg.dec(p.getOrElse(2) { "" })
        }
        osel = os2
        keys = k; upd = u; ad = a; kdev = kd; kn = kn2; roles = rl; ubans = ub; news = newsFs ?: nw; online = on; sess = se; fast = fa; fcmApp = fc; ai = aiOn; bans = bn; relay = rel; fsProj = fp; fsKey = fk; fsDb = fd; fsBase = fb; free = fr; both = bo; pkeys = pk; pin = pn
    }

    /** Abonelik metnini sunucu listesine çevirir (desteklenmeyen satırlar atlanır). */
    @Volatile var needUpd = false   // 1.47: bot diňe has täze wersiýa rugsat berýär (#tvx) — sanaw ýok, täzelemeli
    private fun bsha(s: String) = java.security.MessageDigest.getInstance("SHA-256").digest(s.toByteArray(Charsets.UTF_8))
    private fun bhex(b: ByteArray) = b.joinToString("") { "%02x".format(it) }
    private fun bhmac(k: ByteArray, d: ByteArray) = javax.crypto.Mac.getInstance("HmacSHA256").run { init(javax.crypto.spec.SecretKeySpec(k, "HmacSHA256")); doFinal(d) }
    private fun b64u(s: String) = android.util.Base64.decode(s, android.util.Base64.URL_SAFE or android.util.Base64.NO_PADDING or android.util.Base64.NO_WRAP)
    private fun normKey(k: String) = k.uppercase().filter { it.isLetterOrDigit() }.chunked(4).joinToString("-")

    /** 1.47.16: Premium zarpyny (#tvpk/#tvpb) açary / eýe açar sözi bilen açýar — açyp bolmasa kilitli at. */
    private fun openPrem(creds: List<Pair<String, String>>, pk: String, pb: String): String? {
        val sp = pk.trim().split(Regex("\\s+")); if (sp.isEmpty()) return null
        val ks = sp[0]; val wraps = if (sp.size > 1) sp[1] else "-"
        for ((p, c) in creds) {
            val id = bhex(bhmac(bsha(p + "i|" + c), ks.toByteArray())).substring(0, 12)
            for (w in wraps.split(",")) {
                val dot = w.indexOf('.'); if (dot < 0 || w.substring(0, dot) != id) continue
                val wb = runCatching { b64u(w.substring(dot + 1)) }.getOrNull() ?: continue
                if (wb.size < 32) continue
                val unk = bhmac(bsha(p + "w|" + c), ks.toByteArray())
                val ck = ByteArray(32) { (wb[it].toInt() xor unk[it].toInt()).toByte() }
                Msg.decK(bhex(ck), pb)?.let { return it }
            }
        }
        return null
    }

    /** #tvy-niň içindäki Premium zarpyny hakyky kodlara (açar bolsa) ýa kilitli atlara öwürýär. */
    private fun expandPrem(dec: String): String {
        val lines = dec.lineSequence().map { it.trim() }.toList()
        val pv = lines.firstOrNull { it.startsWith("#tvpv:") }?.substringAfter(" ")?.trim() ?: return dec
        val pk = lines.firstOrNull { it.startsWith("#tvpk:") }?.substringAfter("#tvpk:")?.trim()
        val pb = lines.firstOrNull { it.startsWith("#tvpb:") }?.substringAfter(" ")?.trim()
        val ctx = State.app
        if (pk != null && pb != null && ctx != null) {
            val creds = ArrayList<Pair<String, String>>()
            Lic.saved(ctx)?.let { creds.add("tvp" to normKey(it)) }
            if (roles[Msg.dev(ctx)]?.first == "o") Msg.admPw(ctx)?.let { creds.add("tva" to it.replace(Regex("\\s+"), "").uppercase()) }
            if (creds.isNotEmpty()) openPrem(creds, pk, pb)?.let { return dec + "\n" + it }
        }
        val sb = StringBuilder(dec)
        runCatching {
            val arr = org.json.JSONArray(String(b64u(pv), Charsets.UTF_8))
            for (i in 0 until arr.length()) {
                val e = arr.getJSONArray(i); val scheme = e.getString(0).ifEmpty { "vless" }
                sb.append("\n").append(scheme).append("://x@10.255.255.255:").append(900 + i).append("#").append(e.getString(1))
            }
        }
        return sb.toString()
    }

    /** 1.47.16: #tvy (gol şahadatnamasyna bagly) ýa köne #tvx şifrini açyp düz sanawa öwürýär. */
    fun decode(text: String): String {
        val raw = body(text); val lines = raw.lines()
        fun outer() = lines.filterNot { val t = it.trim(); t.startsWith("#tvy:") || t.startsWith("#tvx:") }.joinToString("\n")
        fun outerMeta() = lines.filter { val t = it.trim(); t.startsWith("#") && !t.startsWith("#tvy:") && !t.startsWith("#tvx:") }.joinToString("\n")   // 1.47.17: köne programmalar üçin «Täze wersiýany gurnaň» setiri görünmesin
        val own = State.app?.let { Msg.ver(it) } ?: "0"
        val yl = lines.firstOrNull { it.trim().startsWith("#tvy:") }?.trim()
        val xl = lines.firstOrNull { it.trim().startsWith("#tvx:") }?.trim()
        if (yl != null) {
            val p = yl.split(Regex("\\s+"))
            if (p.size >= 5 && (own == "0" || !Upd.newer(p[1], own))) {
                val dec = runCatching { N.d(State.app, p[2], p[3], p[4]) }.getOrNull()?.let { String(it, Charsets.UTF_8) }
                if (dec != null) { needUpd = false; return outerMeta() + "\n" + expandPrem(dec) }
            }
        }
        if (xl != null) {
            val p = xl.split(Regex("\\s+"))
            if (p.size >= 3 && (own == "0" || !Upd.newer(p[1], own))) {
                val dec = Msg.dec(p[2])
                if (dec != null) { needUpd = false; return outerMeta() + "\n" + dec }
            }
        }
        if (yl != null || xl != null) { needUpd = true; return outer() }
        return raw
    }

    fun parse(text: String): List<Server> {
        val body = body(text)
        return body.lineSequence().map { it.trim() }
            .filter { it.isNotEmpty() && !it.startsWith("#") }
            .mapNotNull { line ->
                val scheme = line.substringBefore("://").lowercase()
                val proto = when (scheme) {
                    "hysteria2", "hy2" -> "Hysteria"
                    "ss" -> "Shadowsocks"
                    "vless" -> "VLESS"
                    else -> return@mapNotNull null
                }
                val name = Cfg.dec(line.substringAfter('#', ""))
                val (flag, country, title) = splitName(name)
                // 1.47: Özbegistan / Gazagystan serwerleri hem PUBG (öz baýdagy bilen)
                val game = name.contains("🎮") || flag == "🇺🇿" || flag == "🇰🇿" || Regex("pubg|gaming|oýun|game|uzbek|kazak|kazakh", RegexOption.IGNORE_CASE).containsMatchIn(name)
                val ru = game || flag == "🇷🇺" || country.equals("Russia", true) || country.equals("Rossiýa", true)
                if (game) Server(flag.ifEmpty { "🇷🇺" }, country.ifEmpty { "Russia" }, title, proto, line, true, true)
                else Server(flag, country, title, proto, line, false, ru)
            }.toList().numbered()
    }

    /** Aynı adlı sunucular ayırt edilsin: ikincisine «2», üçüncüsüne «3»… */
    private fun List<Server>.numbered(): List<Server> {
        val seen = HashMap<String, Int>()
        return map { s ->
            val k = s.flag + s.country + s.title
            val n = (seen[k] ?: 0) + 1
            seen[k] = n
            if (n == 1) s else s.copy(title = (s.title.ifEmpty { s.country }) + " $n")
        }
    }

    /** "🇳🇱 Netherlands · 🧡 Orange Express" → (🇳🇱, Netherlands, Orange Express) */
    fun splitName(name: String): Triple<String, String, String> {
        val a = name.substringBefore(" · ").trim()
        val b = if (name.contains(" · ")) name.substringAfter(" · ").trim() else ""
        var i = 0
        val sb = StringBuilder()
        while (i < a.length) {
            val cp = a.codePointAt(i)
            if (cp !in 0x1F1E6..0x1F1FF) break
            sb.appendCodePoint(cp); i += Character.charCount(cp)
        }
        val flag = if (sb.isEmpty()) "🌐" else sb.toString()
        val country = a.substring(i).trim().ifEmpty { a }
        return Triple(flag, country, stripLead(b))
    }

    private fun stripLead(s: String): String {
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            if (Character.isLetterOrDigit(cp)) break
            i += Character.charCount(cp)
        }
        return s.substring(i).trim()
    }

    /** Aboneliği indirir; başarılıysa şifreli önbelleğe yazar. Hata olursa önbellek kullanılır. */
    @Volatile private var vpsBadUntil = 0L
    /** 1.45.3: sanaw ilki öz VPS-den (bot n/sub ýazýar — Türkmenistanda VPN-siz çalt); işlemese Google Drive-dan; ikisi hem bolmasa — ýatdaky sanaw. */
    private fun fromVps(ctx: Context, timeoutMs: Int): Boolean {
        if (!Fs.vps() || System.currentTimeMillis() < vpsBadUntil) return false
        val g = runCatching { Fs.get("n/sub", minOf(timeoutMs, 4000)) }.getOrNull()
        val at = g?.second?.takeIf { it.length >= 19 }?.let { ts -> runCatching { java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", java.util.Locale.US)
            .apply { timeZone = java.util.TimeZone.getTimeZone("UTC") }.parse(ts.take(19))?.time }.getOrNull() } ?: 0L
        // bot her 30 minutda täzeden ýazýar — 3 sagatdan köne bolsa (bot VPS-e ýazyp bilmeýär) Drive-dan alynýar
        val t = if (System.currentTimeMillis() - at > 3 * 3600_000L) null else g?.first?.let { Msg.dec(it) ?: it }   // diňe bot ýazyp bilýär (n/); şifrsiz hem kabul
        val exp = t?.let { decode(it) }
        val l = exp?.let { parse(it) }.orEmpty()
        if (exp == null || l.isEmpty()) { vpsBadUntil = System.currentTimeMillis() + 120_000L; return false }
        meta(exp); list = keepActive(l); okAt = System.currentTimeMillis(); src = "vps"
        runCatching { Box.write(ctx, t) }
        return true
    }
    @Volatile var src = ""   // soňky sanaw nireden: "vps" / "drive"

    fun refresh(ctx: Context, timeoutMs: Int = 8000): Boolean {
        if (fromVps(ctx, timeoutMs)) return true
        val ok = runCatching {
            val c = URL(N.u()).openConnection() as HttpURLConnection
            c.connectTimeout = timeoutMs; c.readTimeout = timeoutMs
            c.instanceFollowRedirects = true
            try {
                if (c.responseCode != 200) return@runCatching false
                val t = c.inputStream.use { it.readBytes() }.toString(Charsets.UTF_8)
                val exp = decode(t)
                val l = parse(exp)
                meta(exp)   // key / sürüm / reklam satırları sunucu olmasa da okunur
                if (l.isEmpty()) return@runCatching false
                list = keepActive(l); okAt = System.currentTimeMillis(); src = "drive"
                Box.write(ctx, t)
                true
            } finally { c.disconnect() }
        }.getOrDefault(false)
        if (!ok && list.isEmpty()) load(ctx)
        return ok
    }

    /** Aynı Drive anahtarıyla başka bir dosyanın linki (güncelleme APK'sı için). */
    fun fileUrl(fid: String) = N.u().replace(Regex("/files/[\\w-]+"), "/files/$fid")

    fun load(ctx: Context) {
        if (list.isNotEmpty()) return
        Box.read(ctx)?.let { val exp = decode(it); list = parse(exp); meta(exp) }
    }

    /** 1.47.16: açar / admin girişinden soň Premium-y ýatdaky sanawdan derrew açmak (tor garaşmazdan). */
    fun recheck(ctx: Context) {
        Box.read(ctx)?.let { val exp = decode(it); val l = parse(exp); if (l.isNotEmpty()) { meta(exp); list = keepActive(l) } }
    }
}

/** Önbellek Android Keystore anahtarıyla AES-GCM şifreli tutulur; anahtar cihazdan çıkarılamaz. */
private object Box {
    private const val ALIAS = "yol_c"
    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ALIAS, null) as SecretKey?)?.let { return it }
        val g = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        g.init(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        return g.generateKey()
    }
    private fun f(ctx: Context) = File(ctx.noBackupFilesDir, "c")

    fun write(ctx: Context, s: String) = runCatching {
        val c = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val enc = c.doFinal(s.toByteArray(Charsets.UTF_8))
        f(ctx).writeBytes(byteArrayOf(c.iv.size.toByte()) + c.iv + enc)
    }

    fun read(ctx: Context): String? = runCatching {
        val b = f(ctx).readBytes()
        val n = b[0].toInt()
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, b, 1, n))
        String(c.doFinal(b, 1 + n, b.size - 1 - n), Charsets.UTF_8)
    }.getOrNull()
}
