package tm.yol.vpn

import android.graphics.Bitmap
import android.view.View
import org.junit.Assume
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.shadows.ShadowLooper
import java.io.File

/** Ekranların görüntüsünü alır (sadece -Dshots=dizin verilince çalışır). */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w393dp-h852dp-xxhdpi")
class Shots {
    private val out = System.getProperty("shots") ?: ""

    private val raw = """
hysteria2://a@10.0.0.1:1?sni=a#🇫🇷 France · 🌅 Alps Summit
hysteria2://a@10.0.0.2:2?sni=a#🇳🇱 Netherlands · 🧡 Orange Express
hysteria2://a@10.0.0.3:3?sni=a#🇩🇪 Germany · 🌲 Black Forest
hysteria2://a@10.0.0.4:4?sni=a#🇬🇧 United Kingdom · 👑 Royal Edge
ss://YWVzLTI1Ni1nY206cA==@10.0.0.5:5#🇷🇺 Russia · 🎮 PUBG Gaming Server
ss://YWVzLTI1Ni1nY206cA==@10.0.0.6:6#🇹🇷 Türkiye · 🌙 Crescent Link
    """.trimIndent()

    private fun snap(a: Main, name: String) {
        repeat(30) { ShadowLooper.idleMainLooper(); Thread.sleep(20) }
        val v: View = a.window.decorView
        val w = 393 * 3; val h = 852 * 3
        v.measure(View.MeasureSpec.makeMeasureSpec(w, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(h, View.MeasureSpec.EXACTLY))
        v.layout(0, 0, w, h)
        val b = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        v.draw(android.graphics.Canvas(b))
        File(out).mkdirs()
        File(out, "$name.png").outputStream().use { b.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    private fun page(a: Main, p: String) {
        val f = Main::class.java.getDeclaredField("ready"); f.isAccessible = true; f.set(a, true)
        val en = Class.forName("tm.yol.vpn.Main\$Page")
        val m = Main::class.java.getDeclaredMethod("show", en); m.isAccessible = true
        m.invoke(a, en.enumConstants!!.first { it.toString() == p })
    }

    @Test fun all() {
        Assume.assumeTrue(out.isNotEmpty())
        Sub.list = Sub.parse(raw)
        val a = Robolectric.buildActivity(Main::class.java).setup().get()
        snap(a, "0_acilis")
        page(a, "MAIN"); snap(a, "1_ana_kapali")
        State.active = Sub.list[0]; State.now = State.ON; page(a, "MAIN"); snap(a, "2_ana_bagli")
        Sub.upd = mapOf("all" to ("9.9" to "X")); page(a, "MAIN"); snap(a, "3_guncelleme"); Sub.upd = emptyMap()
        val om = Main::class.java.getDeclaredMethod("openMenu"); om.isAccessible = true; om.invoke(a); snap(a, "4_menu")
        val cm = Main::class.java.getDeclaredMethod("closeMenu"); cm.isAccessible = true; cm.invoke(a)
        page(a, "SERVERS"); snap(a, "5_serverler")
        page(a, "SPEED"); snap(a, "6_hiz")
        page(a, "SETTINGS"); snap(a, "7_ayarlar")
        page(a, "INFO"); snap(a, "8_bilgi")
        // reklam: 4:3 deneme resmi önbelleğe konur
        val bm = Bitmap.createBitmap(800, 600, Bitmap.Config.ARGB_8888); android.graphics.Canvas(bm).apply {
            drawColor(android.graphics.Color.rgb(200, 40, 60))
            drawText("REKLAM 800x600", 200f, 300f, android.graphics.Paint().apply { textSize = 60f; color = android.graphics.Color.WHITE })
        }
        File(a.cacheDir, "ad_TEST").outputStream().use { bm.compress(Bitmap.CompressFormat.PNG, 100, it) }
        Sub.ad = "TEST" to "https://t.me/x"
        page(a, "MAIN"); repeat(20) { ShadowLooper.idleMainLooper(); Thread.sleep(50) }; snap(a, "9_reklam")
        Sub.ad = null
        State.now = State.OFF
    }
}
