package tm.yol.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import java.security.KeyPairGenerator
import java.security.spec.ECGenParameterSpec
import javax.crypto.KeyAgreement

/** Hususy habarlar: iki tarap şol bir syry hasaplaýar, başga açar bilen açylmaýar; nyşanlar we köp adamlyk açar. */
@RunWith(RobolectricTestRunner::class)
class ChatTest {
    @Test fun e2e() {
        val c = RuntimeEnvironment.getApplication()
        val myPub = Chat.pub(c)
        assertEquals(myPub, Chat.pub(c))                                         // açar saklanýar
        val peer = KeyPairGenerator.getInstance("EC").run { initialize(ECGenParameterSpec("secp256r1")); generateKeyPair() }
        val peerPub = android.util.Base64.encodeToString(peer.public.encoded, android.util.Base64.NO_WRAP)
        val mine = Chat.secret(c, peerPub)!!
        // garşydaş tarapda: öz hususy açary + meniň açyk açarym
        val kf = java.security.KeyFactory.getInstance("EC")
        val ka = KeyAgreement.getInstance("ECDH"); ka.init(peer.private)
        ka.doPhase(kf.generatePublic(java.security.spec.X509EncodedKeySpec(android.util.Base64.decode(myPub, 0))), true)
        val theirs = java.security.MessageDigest.getInstance("SHA-256").digest("tvdm|".toByteArray() + ka.generateSecret()).joinToString("") { "%02x".format(it) }
        assertEquals(mine, theirs)
        val box = Msg.encK("dm|$mine", "{\"x\":\"Salam 🇹🇲\"}")
        assertEquals("{\"x\":\"Salam 🇹🇲\"}", Msg.decK("dm|$theirs", box))
        val other = KeyPairGenerator.getInstance("EC").run { initialize(ECGenParameterSpec("secp256r1")); generateKeyPair() }
        val bad = Chat.secret(c, android.util.Base64.encodeToString(other.public.encoded, android.util.Base64.NO_WRAP))!!
        assertNotEquals(mine, bad); assertNull(Msg.decK("dm|$bad", box))       // üçünji adam açyp bilmeýär
        assertEquals(Chat.room("aaaaaaaaaaaa", "bbbbbbbbbbbb"), Chat.room("bbbbbbbbbbbb", "aaaaaaaaaaaa"))
    }

    @Test fun rolesAndMultiKeys() {
        val c = RuntimeEnvironment.getApplication()
        c.getSharedPreferences("p", 0).edit().putString("dev", "0123456789ab").commit()
        // subbot.py: «#tvrole: dev o b64(nik)», «#tvk: özet bitiş telefonlar n»
        Sub.meta("#tvrole: 0123456789ab o S3VydWN1\n#tvrole: zz a x\n#tvk: k1 0 aaaaaaaaaaaa 3\n#tvk: k2 0 aaaaaaaaaaaa,bbbbbbbbbbbb 2\n#tvk: k3 0 - 5\nss://x@1.1.1.1:1#a")
        assertEquals("o" to "Kurucu", Sub.roles["0123456789ab"]); assertNull(Sub.roles["zz"])
        assertEquals(false, Lic.full(c, "k1"))     // 1/3 — ýer bar
        assertEquals(true, Lic.full(c, "k2"))      // 2/2 — doly
        assertEquals(false, Lic.full(c, "k3"))     // heniz hiç kim
        assertEquals(listOf("aaaaaaaaaaaa", "bbbbbbbbbbbb"), Lic.devs("k2"))
    }
}
