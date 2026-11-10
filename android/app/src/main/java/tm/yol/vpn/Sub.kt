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
}

/** Abonelikteki bir sunucu. uri yalnız bellekte ve şifreli önbellekte durur, ekranda gösterilmez. */
data class Server(val flag: String, val country: String, val title: String, val proto: String, val uri: String,
                  val game: Boolean = false, val ru: Boolean = false) {
    /** Seçimi hatırlamak için: abonelik karışsa da aynı sunucu aynı kalır. */
    val key get() = flag + "|" + runCatching { Cfg.link(uri).let { "${it.host}:${it.port}" } }.getOrDefault(title)
}

object Sub {
    @Volatile var list: List<Server> = emptyList()

    /** Abonelik metnini sunucu listesine çevirir (desteklenmeyen satırlar atlanır). */
    fun parse(text: String): List<Server> {
        val body = text.trim().let { t ->
            if (t.contains("://")) t else runCatching {
                String(android.util.Base64.decode(t, android.util.Base64.DEFAULT), Charsets.UTF_8)
            }.getOrDefault(t)
        }
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
                val game = name.contains("🎮") || Regex("pubg|gaming|oýun|game", RegexOption.IGNORE_CASE).containsMatchIn(name)
                val ru = flag == "🇷🇺" || country.equals("Russia", true) || country.equals("Rossiýa", true)
                Server(flag, country, title, proto, line, game, ru)
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
    fun refresh(ctx: Context, timeoutMs: Int = 8000): Boolean {
        val ok = runCatching {
            val c = URL(N.u()).openConnection() as HttpURLConnection
            c.connectTimeout = timeoutMs; c.readTimeout = timeoutMs
            c.instanceFollowRedirects = true
            try {
                if (c.responseCode != 200) return@runCatching false
                val t = c.inputStream.use { it.readBytes() }.toString(Charsets.UTF_8)
                val l = parse(t)
                if (l.isEmpty()) return@runCatching false
                list = l
                Box.write(ctx, t)
                true
            } finally { c.disconnect() }
        }.getOrDefault(false)
        if (!ok && list.isEmpty()) load(ctx)
        return ok
    }

    fun load(ctx: Context) {
        if (list.isNotEmpty()) return
        Box.read(ctx)?.let { list = parse(it) }
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
