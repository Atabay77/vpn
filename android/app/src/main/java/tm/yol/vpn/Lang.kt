package tm.yol.vpn

import android.content.Context

/** Üç dil: Türkmençe (varsayılan), Rusça, Türkçe. t("tm", "ru", "tr") */
object Lang {
    val codes = listOf("tk", "ru", "tr")
    val flags = mapOf("tk" to "🇹🇲", "ru" to "🇷🇺", "tr" to "🇹🇷")
    val names = mapOf("tk" to "Türkmençe", "ru" to "Русский", "tr" to "Türkçe")
    @Volatile var cur = "tk"

    fun init(ctx: Context) { cur = ctx.getSharedPreferences("p", 0).getString("lang", "tk") ?: "tk" }
    fun set(ctx: Context, l: String) { cur = l; ctx.getSharedPreferences("p", 0).edit().putString("lang", l).apply() }

    fun t(tk: String, ru: String, tr: String) = when (cur) { "ru" -> ru; "tr" -> tr; else -> tk }
}

fun t(tk: String, ru: String, tr: String) = Lang.t(tk, ru, tr)
