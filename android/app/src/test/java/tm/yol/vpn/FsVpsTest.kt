package tm.yol.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import java.io.File
import java.net.ServerSocket
import java.net.URL

/** 1.41: programyň Firestore soraglary öz VPS-de (relay.py-daky meňzeş) — hakyky serwer bilen. */
@RunWith(RobolectricTestRunner::class)
class FsVpsTest {
    @Test fun vps() {
        val relay = listOf("../../relay/relay.py", "../relay/relay.py", "relay/relay.py").map { File(it) }.firstOrNull { it.exists() }
        assumeTrue("relay.py tapylmady", relay != null)
        val port = ServerSocket(0).use { it.localPort }
        val data = kotlin.io.path.createTempDirectory("tvrelay").toFile()
        val pb = ProcessBuilder("python3", relay!!.absolutePath).redirectErrorStream(true)
        pb.environment()["PORT"] = port.toString(); pb.environment()["DATA"] = data.absolutePath
        val pr = pb.start()
        try {
            var up = false
            for (i in 0 until 50) { up = runCatching { URL("http://127.0.0.1:$port/health").readText().let { it.startsWith("ok ") && it.contains(" fs") } }.getOrDefault(false); if (up) break; Thread.sleep(100) }
            assertTrue("relay başlamady", up)
            Sub.meta("#tvdb: http://127.0.0.1:$port\n#tvrel: http://127.0.0.1:$port\nss://x@1.1.1.1:1#a")
            assertTrue(Fs.vps()); assertTrue(Fs.on())
            // Global chat: goýmak, tertip, «t > soňky», desc
            assertTrue(Fs.write("g/aaa", "v1.one")); Thread.sleep(5)
            assertTrue(Fs.write("g/bbb", "v1.two"))
            assertFalse(Fs.write("g/bbb", "v1.again"))                  // şol id — ýok (exists:false)
            val all = Fs.query("", "g", null, 10)!!
            assertEquals(listOf("aaa", "bbb"), all.map { it.first })
            assertEquals(listOf("bbb"), Fs.query("", "g", all[0].third, 10)!!.map { it.first })
            assertEquals(listOf("bbb", "aaa"), Fs.query("", "g", null, 10, desc = true)!!.map { it.first })
            assertTrue(Fs.sec(all[0].third) > 1_700_000_000L)
            // profil (p/ üýtgedip bolýar), ýok resminama — null
            assertNull(Fs.get("p/0123456789ab"))
            assertTrue(Fs.write("p/0123456789ab", "v1.p1", create = false)); assertTrue(Fs.write("p/0123456789ab", "v1.p2", create = false))
            assertEquals("v1.p2", Fs.get("p/0123456789ab")!!.first)
            // DM otagy (subkolleksiýa), bota habar (m/ okap bolmaýar), telefona habar (d/ ýazyp bolmaýar)
            assertTrue(Fs.write("x/aa_bb/i/m1", "v1.dm"))
            assertEquals(listOf("m1"), Fs.query("x/aa_bb", "i", null, 60)!!.map { it.first })
            assertTrue(Fs.write("m/q1", "v1.tobot"))
            assertNull(Fs.query("", "m", null, 10))
            assertFalse(Fs.write("d/0123456789ab/i/1", "v1.fake"))
            assertEquals(404, Fs.ping())                               // «açylýar» (ýok resminama)
        } finally {
            pr.destroy(); pr.waitFor(); data.deleteRecursively(); Sub.meta("")
        }
    }
}
