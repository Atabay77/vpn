package tm.yol.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment

/** Bot (Python) bilen birmeňzeş şifrlemek, çagyryş kody we gizli setirler. */
@RunWith(RobolectricTestRunner::class)
class MsgTest {
    private val pt = "{\"k\":\"tk\",\"t\":\"Salam ýaşyl ň 🇹🇲 " + "x".repeat(40) + "\"}"
    // subbot.py: app_enc("TESTFID123", pt, bytes(range(12)))
    private val py = "v1.AAECAwQFBgcICQoLvSQ9zQRJWClYyPGIwzn-FdMQNBIsJSJn1mcf0kPnkHfEJ24jNkDpcKmR4AgL854dhyCjxXKr3-dCIQG1IKRdwiVAJmnnuXlf7acc6mO2ltGnFyw5Cuw4RUOHlcAG_Zi-yKWH"

    @Test fun crypto() {
        assertEquals(py, Msg.encK("TESTFID123", pt, ByteArray(12) { it.toByte() }))
        assertEquals(pt, Msg.decK("TESTFID123", py))
        assertNull(Msg.decK("BASKA", py))                                   // başga açar: açylmaýar
        assertNull(Msg.decK("TESTFID123", py.dropLast(2) + "AA"))          // üýtgedilen habar: kabul edilmeýär
        val r = Msg.encK("F", "salam"); assertEquals("salam", Msg.decK("F", r))
    }

    @Test fun admin() {
        // subbot.py: apw_id(" adm-abcd-efgh-jkmn ") == "8e8669d3d881065d" (boşluk aýrylýar, baş harp)
        assertEquals("8e8669d3d881065d", Msg.admId(" adm-abcd-efgh-jkmn "))
        val c = RuntimeEnvironment.getApplication()
        Msg.adm(c, org.json.JSONObject().put("a", "login").put("pw", " ADM-ABCD-EFGH-JKMN "))
        assertEquals("ADM-ABCD-EFGH-JKMN", Msg.admPw(c))
        val q = org.json.JSONArray(c.getSharedPreferences("msg", 0).getString("q", "[]"))
        val o = org.json.JSONObject(q.getString(q.length() - 1))
        assertEquals("8e8669d3d881065d", o.getString("aid"))
        val r = org.json.JSONObject(Msg.decK("adm|ADM-ABCD-EFGH-JKMN", o.getString("x"))!!)
        assertEquals("login", r.getString("a")); assertEquals(false, r.has("pw"))   // açar söz özi iberilmeýär
        Msg.adm(c, org.json.JSONObject().put("a", "logout")); assertNull(Msg.admPw(c))
        // giriş → şifrli jogap; soň şifrsiz «nädogry» (başga biri iberen) admini çykarmaýar; şifrli «busy» çykarýar
        val pw = "ADM-ABCD-EFGH-JKMN"
        Msg.adm(c, org.json.JSONObject().put("a", "login").put("pw", pw))
        fun x(o: String) = org.json.JSONObject().put("k", "adm").put("x", Msg.encK("adm|$pw", o))
        Msg.admIn(c, x("{\"ok\":true,\"me\":{\"role\":\"f\"}}"))
        assertEquals("f", Msg.admMe(c)!!.getString("role"))
        Msg.admIn(c, org.json.JSONObject().put("k", "adm").put("err", "bad"))
        assertEquals(pw, Msg.admPw(c))
        Msg.admIn(c, x("{\"err\":\"busy\"}"))
        assertNull(Msg.admPw(c))
        Msg.take(c)
    }

    @Test fun codeAndMeta() {
        val c = RuntimeEnvironment.getApplication()
        c.getSharedPreferences("p", 0).edit().putString("dev", "0123456789ab").commit()
        assertEquals("TM-6F7HQ", Msg.code(c))                               // subbot.py app_ref_code("0123456789ab")
        Sub.meta("#tvk: aaa 0 0123456789ab\n#tvk: bbb 0 ffffffffffff\n#tvk: ccc 0\n#tvn: n1 1700000000 eyJ0IjoiU2FsYW0iLCJ4IjoiSGFiYXIifQ\n#tvon: 42\n#tvai: 1\n#tvban: d1,d2\n#tvrel: http://10.1.2.3:8090/\nss://x@1.1.1.1:1#a")
        assertEquals("0123456789ab", Sub.kdev["aaa"]); assertNull(Sub.kdev["ccc"])
        assertEquals(1, Sub.news.size); assertEquals("{\"t\":\"Salam\",\"x\":\"Habar\"}", Sub.news[0].third)
        assertEquals(42, Sub.online); assertEquals(true, Sub.ai); assertEquals(setOf("d1", "d2"), Sub.bans); assertEquals("http://10.1.2.3:8090", Sub.relay)
    }
}
