package tm.yol.vpn

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.ServerSocket
import kotlin.concurrent.thread

class PingerTest {
    private val vless = "vless://11111111-2222-3333-4444-555555555555@1.2.3.4:443?type=tcp&security=reality&pbk=abc&sni=x.com&fp=chrome#A"
    private val ss = "ss://aes-256-gcm:pw@5.6.7.8:8388#B"

    @Test fun configOneCoreManyServers() {
        val list = listOf(Server("🇩🇪", "Germaniýa", "A", "VLESS", vless), Server("🇳🇱", "N", "B", "SS", "bad://x"), Server("🇫🇷", "F", "C", "SS", ss))
        val (cfg, used) = Pinger.config(list, intArrayOf(31001, 31002, 31003))
        val j = JSONObject(cfg)
        assertEquals(setOf(0, 2), used.keys)   // goldanmaýan kod geçildi
        val ins = j.getJSONArray("inbounds"); val outs = j.getJSONArray("outbounds"); val rules = j.getJSONObject("routing").getJSONArray("rules")
        assertEquals(2, ins.length()); assertEquals(3, outs.length()); assertEquals(2, rules.length())
        assertEquals("dokodemo-door", ins.getJSONObject(0).getString("protocol"))
        assertEquals("www.gstatic.com", ins.getJSONObject(0).getJSONObject("settings").getString("address"))
        assertEquals(31003, ins.getJSONObject(1).getInt("port"))
        assertEquals("o0", outs.getJSONObject(0).getString("tag")); assertEquals("o2", outs.getJSONObject(1).getString("tag"))
        assertEquals("o2", rules.getJSONObject(1).getString("outboundTag"))
        assertEquals("i2", rules.getJSONObject(1).getJSONArray("inboundTag").getString(0))
    }

    /** Ýerli «serwer»: bir birikmede iki sorag (KeepAlive); ikinjisi çalt. */
    @Test fun keepAliveTakesBest() {
        val ss = ServerSocket(0)
        thread {
            ss.accept().use { c ->
                val inp = c.getInputStream().bufferedReader(); val out = c.getOutputStream()
                for (i in 0 until 2) {
                    while (true) { val l = inp.readLine() ?: return@use; if (l.isEmpty()) break }
                    if (i == 0) Thread.sleep(300)   // birinji — birikme gurulýar (haýal)
                    out.write("HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n".toByteArray()); out.flush()
                }
            }
        }
        val ms = Pinger.measure(ss.localPort)
        ss.close()
        assertTrue("ms=$ms", ms in 1..250)   // ikinji sorag (300 ms däl)
    }

    @Test fun deadServerIsMinusOne() {
        val ss = ServerSocket(0)
        thread { ss.accept().use { it.getInputStream().read(); } }   // jogap bermän ýapylýar (Xray çykyşy işlemedi)
        assertEquals(-1L, Pinger.measure(ss.localPort, firstMs = 1500))
        ss.close()
    }

    @Test fun bodyIsSkipped() {
        val ss = ServerSocket(0)
        thread {
            ss.accept().use { c ->
                val inp = c.getInputStream().bufferedReader(); val out = c.getOutputStream()
                for (i in 0 until 2) {
                    while (true) { val l = inp.readLine() ?: return@use; if (l.isEmpty()) break }
                    out.write("HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\npong".toByteArray()); out.flush()
                }
            }
        }
        assertTrue(Pinger.measure(ss.localPort, host = "ec2.eu-central-1.amazonaws.com", path = "/ping") > 0)
        ss.close()
    }
}
