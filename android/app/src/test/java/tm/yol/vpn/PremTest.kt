package tm.yol.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment

/** 1.43: Premium — mugt serwerler (#tvfree), Premium açar, satyjy roly, Premium telefonlar. */
@RunWith(RobolectricTestRunner::class)
class PremTest {
    @Test fun gating() {
        val c = RuntimeEnvironment.getApplication()
        c.getSharedPreferences("p", 0).edit().putString("dev", "0123456789ab").remove("key").commit()
        val free = Server("🇩🇪", "Germaniýa", "Türkmen VPN", "VLESS", "vless://u@1.1.1.1:443?type=tcp#a")
        val prem = Server("🇫🇷", "Fransiýa", "Türkmen VPN", "VLESS", "vless://u@2.2.2.2:443?type=tcp#b")
        Sub.meta("")
        assertTrue(State.allowed(c, prem))                                     // köne bot (#tvfree ýok) — hemmesi mugt
        val k = "ABCD-EFGH-JKMN"; val h = Lic.hash(k); val exp = System.currentTimeMillis() / 1000 + 86400
        Sub.meta("#tvfree: 1.1.1.1:443,9.9.9.9:8443\n#tvk: $h $exp 0123456789ab\n#tvk: zzz 1 ffffffffffff\n#tvrole: aaaaaaaaaaaa s\n#tvrole: bbbbbbbbbbbb o")
        assertEquals(setOf("1.1.1.1:443", "9.9.9.9:8443"), Sub.free)
        assertFalse(Lic.prem(c))
        assertTrue(State.allowed(c, free)); assertFalse(State.allowed(c, prem))   // Premium ýok — diňe mugt
        Lic.save(c, k)
        assertTrue(Lic.prem(c)); assertTrue(State.allowed(c, prem))                // Premium — hemmesi
        assertEquals(setOf("0123456789ab"), Lic.premDevs())                        // möhleti geçen açar (exp=1) sanalmaýar
        assertEquals("s", Sub.roles["aaaaaaaaaaaa"]?.first); assertEquals("o", Sub.roles["bbbbbbbbbbbb"]?.first)
        // 1.43.4: sowgat açary (#tvkp-da ýok) — wagt çägi ýok, ýöne Premium däl
        Sub.meta("#tvkp: -\n#tvfree: 1.1.1.1:443\n#tvk: $h $exp 0123456789ab")
        assertTrue(Lic.exp(c) != null); assertFalse(Lic.prem(c)); assertFalse(State.allowed(c, prem)); assertTrue(Lic.premDevs().isEmpty())
        Sub.meta("#tvkp: $h\n#tvfree: 1.1.1.1:443\n#tvk: $h $exp 0123456789ab")
        assertTrue(Lic.prem(c)); assertTrue(State.allowed(c, prem))
        Lic.save(c, null)
        Sub.meta("#tvkp: -\n#tvk: $h $exp 0123456789ab")   // 1.47: täze bot, mugt sanaw boş — Premium serwerler açylmaýar
        assertFalse(State.allowed(c, prem)); assertFalse(State.allowed(c, free))
        Sub.meta("#tvkp: -\n#tvfree: 1.1.1.1:443\n#tvrole: 0123456789ab o")   // 1.43.5: eýesi açarsyz hem Premium
        assertTrue(Lic.prem(c)); assertTrue(State.allowed(c, prem))
        Sub.meta("")
    }

    /** 1.44: mugt birikme wagty — admin panelinden (#tvsess), nik bonusy +30 minut, Premium / açar — çäksiz. */
    @Test fun sessionTime() {
        val c = RuntimeEnvironment.getApplication()
        c.getSharedPreferences("p", 0).edit().putString("dev", "0123456789ab").remove("key").remove("nkb").remove("uban").putLong("start", 0).commit()
        Sub.meta("#tvsess: 120\n#tvfree: 1.1.1.1:443")
        assertEquals(120, Sub.sess); assertEquals(120 * 60_000L, Lic.session(c)); assertEquals(120 * 60_000L, Lic.left(c))
        Lic.setBonus(c); assertEquals(150 * 60_000L, Lic.left(c))
        Lic.setStart(c, System.currentTimeMillis() - 60 * 60_000L)
        val l = Lic.left(c)!!; assertTrue(l in 89 * 60_000L..90 * 60_000L)                       // 1 sagat geçdi — 1,5 sagat galdy
        Lic.setStart(c, System.currentTimeMillis() - 200 * 60_000L); assertEquals(0L, Lic.left(c))   // gutardy
        Sub.meta("#tvsess: 0\n#tvfree: 1.1.1.1:443"); assertEquals(null, Lic.left(c))             // wagtsyz
        Sub.meta("#tvsess: 5\n#tvfree: 1.1.1.1:443"); assertEquals(60, Sub.sess)                   // nädogry baha kabul edilmeýär
        Sub.meta("#tvsess: 60\n#tvfree: 1.1.1.1:443\n#tvrole: 0123456789ab o"); assertEquals(null, Lic.left(c))   // eýesi — çäksiz
        val k = "ABCD-EFGH-JKMN"; val h = Lic.hash(k); Lic.save(c, k)
        Sub.meta("#tvsess: 60\n#tvkp: -\n#tvk: $h 0 0123456789ab"); assertEquals(null, Lic.left(c))   // sowgat açary — çäksiz
        Lic.save(c, null); c.getSharedPreferences("p", 0).edit().remove("nkb").putLong("start", 0).commit(); Sub.meta("")
    }
}
