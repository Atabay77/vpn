package tm.yol.vpn

import android.content.Context
import java.security.MessageDigest

/** Key: botun ürettiği XXXX-XXXX-XXXX. Geçerliyse 2 saatlik oturum sınırı kalkar. */
object Lic {
    const val SESSION_MS = 2 * 60 * 60 * 1000L

    fun norm(k: String) = k.uppercase().filter { it.isLetterOrDigit() }.chunked(4).joinToString("-")
    fun hash(k: String): String = MessageDigest.getInstance("SHA-256")
        .digest(("tvk|" + norm(k)).toByteArray()).joinToString("") { "%02x".format(it) }.take(20)

    private fun p(ctx: Context) = ctx.getSharedPreferences("p", 0)
    fun saved(ctx: Context): String? = p(ctx).getString("key", null)
    fun save(ctx: Context, k: String?) = p(ctx).edit().putString("key", k?.let { norm(it) }).apply()

    /** Geçerli keyin bitişi (ms, 0 = süresiz) ya da null (key yok / iptal / süresi dolmuş). */
    fun exp(ctx: Context): Long? {
        val k = saved(ctx) ?: return null
        val e = Sub.keys[hash(k)] ?: return null
        return if (e == 0L || e * 1000 > System.currentTimeMillis()) e * 1000 else null
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
