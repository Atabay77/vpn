package tm.yol.vpn

import android.content.Context
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.security.MessageDigest
import java.util.UUID

/** Anonim kullanım sayacı: rastgele cihaz kimliği + sürüm, ntfy.sh üzerinden bota. Kişisel bilgi yok. */
object Stats {
    private fun id(ctx: Context): String {
        val p = ctx.getSharedPreferences("p", 0)
        return p.getString("sid", null) ?: UUID.randomUUID().toString().replace("-", "").take(12).also { p.edit().putString("sid", it).apply() }
    }

    /** Konu adı programın dosya kimliğinden türetilir; bot da aynısını hesaplar. */
    fun topic(): String? = runCatching {
        val fid = Regex("/files/([\\w-]+)").find(N.u())!!.groupValues[1]
        "tvpn" + MessageDigest.getInstance("SHA-256").digest(fid.toByteArray()).joinToString("") { "%02x".format(it) }.take(16)
    }.getOrNull()

    /** viaTunnel: bağlıyken istek tünel içinden gider (doğrudan erişim engelli olabilir). */
    fun beat(ctx: Context, viaTunnel: Boolean) {
        val tp = topic() ?: return
        val ver = runCatching { ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName }.getOrNull() ?: "0"
        val msg = URLEncoder.encode("hb ${id(ctx)} $ver ${Lang.cur} ${if (viaTunnel) 1 else 0}", "UTF-8")
        val url = "https://ntfy.sh/$tp/publish?message=$msg"
        if (viaTunnel) { runCatching { State.core?.measureDelay(url) }; return }
        runCatching {
            val c = URL(url).openConnection() as HttpURLConnection
            c.connectTimeout = 4000; c.readTimeout = 4000
            c.responseCode; c.disconnect()
        }
    }
}
