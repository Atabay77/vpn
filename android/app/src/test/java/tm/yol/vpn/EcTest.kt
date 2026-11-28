package tm.yol.vpn

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test
import java.security.KeyPairGenerator
import java.security.MessageDigest
import java.security.spec.ECGenParameterSpec
import javax.crypto.KeyAgreement

class EcTest {
    private fun seed(s: String) = MessageDigest.getInstance("SHA-256").digest(s.toByteArray())
    private fun dh(a: java.security.PrivateKey, b: java.security.PublicKey) = KeyAgreement.getInstance("ECDH").run { init(a); doPhase(b, true); generateSecret() }

    @Test fun deterministic() {
        val a = Ec.keyPair(seed("x")); val b = Ec.keyPair(seed("x")); val c = Ec.keyPair(seed("y"))
        assertArrayEquals(a.public.encoded, b.public.encoded)
        assertArrayEquals(a.private.encoded, b.private.encoded)
        assertNotEquals(a.public.encoded.toList(), c.public.encoded.toList())
    }

    @Test fun validKeyAgreement() {
        // nokat egrilikde bolmasa ECDH iki tarapda deň bolmaýar (ýa-da ýalňyşlyk)
        val mine = Ec.keyPair(seed("phone-1"))
        val other = KeyPairGenerator.getInstance("EC").run { initialize(ECGenParameterSpec("secp256r1")); generateKeyPair() }
        assertArrayEquals(dh(mine.private, other.public), dh(other.private, mine.public))
        val two = Ec.keyPair(seed("phone-2"))
        assertArrayEquals(dh(mine.private, two.public), dh(two.private, mine.public))
        assertEquals(91, mine.public.encoded.size)   // X.509 P-256 (Chat.pub bilen birmeňzeş görnüş)
    }
}
