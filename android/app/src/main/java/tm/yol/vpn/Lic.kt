package tm.yol.vpn

import android.content.Context
import java.security.MessageDigest

/** Key: botun ürettiği XXXX-XXXX-XXXX. Geçerliyse 1 saatlik oturum sınırı kalkar. Her key diňe 1 telefonda işleýär. */
object Lic {
    const val SESSION_MS = 60 * 60 * 1000L

    fun norm(k: String) = k.uppercase().filter { it.isLetterOrDigit() }.chunked(4).joinToString("-")
    fun hash(k: String): String = MessageDigest.getInstance("SHA-256")
        .digest(("tvk|" + norm(k)).toByteArray()).joinToString("") { "%02x".format(it) }.take(20)

    private fun p(ctx: Context) = ctx.getSharedPreferences("p", 0)
    fun saved(ctx: Context): String? = p(ctx).getString("key", null)
    fun save(ctx: Context, k: String?) = p(ctx).edit().putString("key", k?.let { norm(it) }).apply()

    /** Geçerli keyin bitişi (ms, 0 = süresiz) ya da null (key yok / iptal / süresi dolmuş). */
    fun exp(ctx: Context): Long? {
        val k = saved(ctx) ?: return null
        val h = hash(k)
        val e = Sub.keys[h] ?: return null
        Sub.kdev[h]?.let { if (it != Msg.dev(ctx)) return null }   // başga telefona baglanan
        return if (e == 0L || e * 1000 > System.currentTimeMillis()) e * 1000 else null
    }

    /** Key ýagdaýy: "ok", "used" (başga telefonda), "bad" (ýok / möhleti geçen). */
    fun status(ctx: Context, k: String): String {
        val h = hash(k); val e = Sub.keys[h] ?: return "bad"
        Sub.kdev[h]?.let { if (it != Msg.dev(ctx)) return "used" }
        return if (e == 0L || e * 1000 > System.currentTimeMillis()) "ok" else "bad"
    }

    // ---- oturum ----
    fun start(ctx: Context): Long = p(ctx).getLong("start", 0)
    fun setStart(ctx: Context, t: Long) = p(ctx).edit().putLong("start", t).apply()

    /** Kalan süre (ms) ya da null = sınırsız (key). */
    fun left(ctx: Context): Long? {
        if (exp(ctx) != null) return null
        val s = start(ctx).takeIf { it > 0 } ?: return SESSION_MS
        return (s + SESSION_MS - System.currentTimeMillis()).coerceAtLeast(0)
    }
}
