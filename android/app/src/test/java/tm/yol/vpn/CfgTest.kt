package tm.yol.vpn

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/** 1.44.2: VLESS / XHTTP — TLS bölekleýji (fm / fragment) we «h3, http/1.1» alpn. */
@RunWith(RobolectricTestRunner::class)
class CfgTest {
    private val fmLink = "vless://2e69b088-6ef3-417f-8247-125cf257fafd@143.204.2.1:443?encryption=none&security=tls&sni=d1ivx1xk58pr8u.cloudfront.net&alpn=h3%2C%20http%2F1.1%2C%20h2&fp=chrome&type=xhttp&mode=auto&host=d1ivx1xk58pr8u.cloudfront.net&path=%2Fcf&fragment=3-3%2C0-1%2Ctlshello%2Cnull&fm=%7B%22tcp%22%3A%5B%7B%22settings%22%3A%7B%22delay%22%3A%220-1%22%2C%22length%22%3A%223-3%22%2C%22packets%22%3A%22tlshello%22%7D%2C%22type%22%3A%22fragment%22%7D%5D%7D#x"
    @Test fun vlessXhttpFragment() {
        val st = Cfg.outbound(fmLink).getJSONObject("streamSettings")
        assertEquals("xhttp", st.getString("network"))
        assertEquals(listOf("h3", "http/1.1", "h2"), st.getJSONObject("tlsSettings").getJSONArray("alpn").let { a -> (0 until a.length()).map { a.getString(it) } })
        val fr = st.getJSONObject("finalmask").getJSONArray("tcp").getJSONObject(0)
        assertEquals("fragment", fr.getString("type")); assertEquals("tlshello", fr.getJSONObject("settings").getString("packets"))
        // köne «fragment=…» (fm ýok)
        val st2 = Cfg.outbound(fmLink.replace(Regex("&fm=[^#]*"), "")).getJSONObject("streamSettings")
        val s2 = st2.getJSONObject("finalmask").getJSONArray("tcp").getJSONObject(0).getJSONObject("settings")
        assertEquals("3-3", s2.getString("length")); assertEquals("0-1", s2.getString("delay")); assertEquals("tlshello", s2.getString("packets"))
        System.getenv("CFG_OUT")?.let { java.io.File(it).writeText(Cfg.full(fmLink, false)) }
        assertTrue(JSONObject(Cfg.full(fmLink, false)).has("outbounds"))
    }
}
