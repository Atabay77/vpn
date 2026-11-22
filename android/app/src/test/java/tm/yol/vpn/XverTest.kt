package tm.yol.vpn

import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/** 1.47: botuň şifrlän kod sanawy (app_enc) programmada açylýar. */
@RunWith(RobolectricTestRunner::class)
class XverTest {
    @Test fun decrypt() {
        val pt = Msg.decK("FIDTEST", "v1.MDEyMzQ1Njc4OWFi5Oi0MD9-qFDvSzWfE4j-9-J6bjHL6nDk5WhhyY9TozJ5li4_At686Swk78kDUU5bG1vSBaBKJsAEVh0zOP_KBDfb6liG_L1kZyJ7E4GyqpcR")
        assertEquals("vless://u@1.2.3.4:443?type=tcp#a\nvless://u@1.2.3.5:443?type=tcp#b", pt)
    }
}
