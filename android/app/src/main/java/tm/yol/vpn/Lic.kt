package tm.yol.vpn

import android.content.Context
import java.security.MessageDigest

/** Key: botun ürettiği XXXX-XXXX-XXXX. Geçerliyse 1 saatlik oturum sınırı kalkar. Her key diňe 1 telefonda işleýär. */
object Lic {
    const val SESSION_MS = 60 * 60 * 1000L    // bot wagt bermese (köne bot)
    const val BONUS_ADD = 30 * 60 * 1000L     // 1.24: profilde nigini üýtgeden — +30 minut
    const val BANNED_MS = 20 * 60 * 1000L     // gadagan edilen: açar işlemeýär, VPN 20 minut

    /** Admin gadagan etdi: bot habar iberdi ýa-da abuna faýlynda (#tvuban). */
    fun banned(ctx: Context): Boolean = p(ctx).getBoolean("uban", false) || Msg.dev(ctx) in Sub.ubans
    fun bonus(ctx: Context) = p(ctx).getBoolean("nkb", false)
    fun kill(ctx: Context) = p(ctx).getBoolean("ks", false)   // 1.28: kill switch
    fun setKill(ctx: Context, on: Boolean) = p(ctx).edit().putBoolean("ks", on).apply()
    fun setBonus(ctx: Context) = p(ctx).edit().putBoolean("nkb", true).apply()
    /** 1.32: eýesi admin panelinden wagtsyz goýdy (gadagan edilene degişli däl). */
    fun unlim(ctx: Context) = !banned(ctx) && Sub.sess == 0
    /** Bir birikmäniň wagty (ms) ýa-da null = wagtsyz. */
    fun session(ctx: Context): Long? {
        if (banned(ctx)) return BANNED_MS
        if (Sub.sess == 0) return null
        val base = Sub.sess * 60_000L
        return if (bonus(ctx)) base + BONUS_ADD else base
    }

    fun norm(k: String) = k.uppercase().filter { it.isLetterOrDigit() }.chunked(4).joinToString("-")
    fun hash(k: String): String = MessageDigest.getInstance("SHA-256")
        .digest(("tvk|" + norm(k)).toByteArray()).joinToString("") { "%02x".format(it) }.take(20)

    private fun p(ctx: Context) = ctx.getSharedPreferences("p", 0)
    fun saved(ctx: Context): String? = p(ctx).getString("key", null)
    fun setBanned(ctx: Context, on: Boolean) = p(ctx).edit().putBoolean("uban", on).apply()
    fun save(ctx: Context, k: String?) {
        val e = p(ctx).edit().putString("key", k?.let { norm(it) })
        if (k != null) {   // 1.44: ulanan açarlaryň taryhy (iň köp 20)
            val nk = norm(k); val h = hist(ctx).filter { it.first != nk } + (nk to System.currentTimeMillis() / 1000)
            e.putString("khist", h.takeLast(20).joinToString("\n") { "${it.first} ${it.second}" })
        }
        e.apply()
    }
    fun hist(ctx: Context): List<Pair<String, Long>> = (p(ctx).getString("khist", null) ?: "").split("\n").mapNotNull { l ->
        val q = l.split(" "); if (q.size == 2 && q[0].length == 14) q[0] to (q[1].toLongOrNull() ?: 0L) else null }
    /** 1.44: Premium açary (satyn alnan / berlen) ýa-da sowgat (diňe wagt çägi ýok). */
    fun isPremKey(k: String) = Sub.pkeys?.contains(hash(k)) ?: true

    /** Geçerli keyin bitişi (ms, 0 = süresiz) ya da null (key yok / iptal / süresi dolmuş). */
    fun exp(ctx: Context): Long? {
        val k = saved(ctx) ?: return null
        if (banned(ctx)) return null
        val h = hash(k)
        val e = Sub.keys[h] ?: return null
        if (full(ctx, h)) return null   // başga telefon(lar)a baglanan, ýer ýok
        return if (e == 0L || e * 1000 > System.currentTimeMillis()) e * 1000 else null
    }

    /** 1.43: Premium — geçerli açar (bot Premium beren / satyn alnan / sowgat). Ähli serwerler we wagt çägi ýok. */
    fun prem(ctx: Context): Boolean = Sub.roles[Msg.dev(ctx)]?.first == "o" ||   // 1.43.5: eýesi hemişe Premium
        (exp(ctx) != null && saved(ctx)?.let { k -> Sub.pkeys?.contains(hash(k)) ?: true } == true)   // 1.43.4: sowgat açarlary Premium däl

    /** 1.43: Premium-ly telefonlar (abuna faýlyndaky açarlardan) — chatda ýalpyldaýan nyşan üçin. */
    fun premDevs(): Set<String> {
        val now = System.currentTimeMillis() / 1000; val out = HashSet<String>()
        val pk = Sub.pkeys
        Sub.keys.forEach { (h, e) -> if ((e == 0L || e > now) && (pk == null || h in pk)) Sub.kdev[h]?.split(',')?.filter { it.length == 12 }?.let { out.addAll(it) } }
        return out
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
        if (exp(ctx) != null || prem(ctx)) return null   // 1.44: Premium (eýesi açarsyz hem) — wagt çägi ýok
        val ses = session(ctx) ?: return null
        val s = start(ctx).takeIf { it > 0 } ?: return ses
        return (s + ses - System.currentTimeMillis()).coerceAtLeast(0)
    }
}
