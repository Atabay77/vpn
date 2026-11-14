package tm.yol.vpn

import android.content.Context
import java.security.MessageDigest

/** Key: botun ürettiği XXXX-XXXX-XXXX. Geçerliyse 1 saatlik oturum sınırı kalkar. Her key diňe 1 telefonda işleýär. */
object Lic {
    const val SESSION_MS = 60 * 60 * 1000L
    const val BONUS_MS = 90 * 60 * 1000L      // 1.24: profilde nigini üýtgeden — 1,5 sagat
    const val BANNED_MS = 20 * 60 * 1000L     // gadagan edilen: açar işlemeýär, VPN 20 minut

    /** Admin gadagan etdi: bot habar iberdi ýa-da abuna faýlynda (#tvuban). */
    fun banned(ctx: Context): Boolean = p(ctx).getBoolean("uban", false) || Msg.dev(ctx) in Sub.ubans
    fun bonus(ctx: Context) = p(ctx).getBoolean("nkb", false)
    fun kill(ctx: Context) = p(ctx).getBoolean("ks", false)   // 1.28: kill switch
    fun setKill(ctx: Context, on: Boolean) = p(ctx).edit().putBoolean("ks", on).apply()
    fun setBonus(ctx: Context) = p(ctx).edit().putBoolean("nkb", true).apply()
    private fun session(ctx: Context) = if (banned(ctx)) BANNED_MS else if (bonus(ctx)) BONUS_MS else SESSION_MS

    fun norm(k: String) = k.uppercase().filter { it.isLetterOrDigit() }.chunked(4).joinToString("-")
    fun hash(k: String): String = MessageDigest.getInstance("SHA-256")
        .digest(("tvk|" + norm(k)).toByteArray()).joinToString("") { "%02x".format(it) }.take(20)

    private fun p(ctx: Context) = ctx.getSharedPreferences("p", 0)
    fun saved(ctx: Context): String? = p(ctx).getString("key", null)
    fun setBanned(ctx: Context, on: Boolean) = p(ctx).edit().putBoolean("uban", on).apply()
    fun save(ctx: Context, k: String?) = p(ctx).edit().putString("key", k?.let { norm(it) }).apply()

    /** Geçerli keyin bitişi (ms, 0 = süresiz) ya da null (key yok / iptal / süresi dolmuş). */
    fun exp(ctx: Context): Long? {
        val k = saved(ctx) ?: return null
        if (banned(ctx)) return null
        val h = hash(k)
        val e = Sub.keys[h] ?: return null
        if (full(ctx, h)) return null   // başga telefon(lar)a baglanan, ýer ýok
        return if (e == 0L || e * 1000 > System.currentTimeMillis()) e * 1000 else null
    }

    /** Key ýagdaýy: "ok", "used" (başga telefonda), "bad" (ýok / möhleti geçen). */
    fun status(ctx: Context, k: String): String {
        val h = hash(k); val e = Sub.keys[h] ?: return "bad"
        if (full(ctx, h)) return "used"
        return if (e == 0L || e * 1000 > System.currentTimeMillis()) "ok" else "bad"
    }

    /** Açara baglanan telefonlar. */
    fun devs(h: String): List<String> = Sub.kdev[h]?.split(',')?.filter { it.isNotBlank() } ?: emptyList()
    /** Bu telefon sanawda ýok we ähli ýerler eýýäm alnan. */
    fun full(ctx: Context, h: String): Boolean { val d = devs(h); return d.isNotEmpty() && Msg.dev(ctx) !in d && d.size >= (Sub.kn[h] ?: 1) }

    // ---- oturum ----
    fun start(ctx: Context): Long = p(ctx).getLong("start", 0)
    fun setStart(ctx: Context, t: Long) = p(ctx).edit().putLong("start", t).apply()

    /** Kalan süre (ms) ya da null = sınırsız (key). */
    fun left(ctx: Context): Long? {
        if (exp(ctx) != null) return null
        val s = start(ctx).takeIf { it > 0 } ?: return session(ctx)
        return (s + session(ctx) - System.currentTimeMillis()).coerceAtLeast(0)
    }
}
