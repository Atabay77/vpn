package tm.yol.vpn

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.DatagramPacket
import java.net.DatagramSocket
import kotlin.concurrent.thread

class DnsTest {
    private val link = "vless://11111111-2222-3333-4444-555555555555@1.2.3.4:443?type=tcp&security=tls&sni=x.com#A"

    @Test fun cfgHasDnsCheckInbound() {
        val j = JSONObject(Cfg.full(link, true, 30000, 30001))
        val ins = j.getJSONArray("inbounds"); val d = (0 until ins.length()).map { ins.getJSONObject(it) }.first { it.getString("tag") == "dnsck" }
        assertEquals(30001, d.getInt("port")); assertEquals("udp", d.getJSONObject("settings").getString("network"))
        val rules = j.getJSONObject("routing").getJSONArray("rules")
        assertTrue((0 until rules.length()).any { rules.getJSONObject(it).optJSONArray("inboundTag")?.getString(0) == "dnsck" && rules.getJSONObject(it).getString("outboundTag") == "dns-out" })
        // köne düzgün (geri bozma): DNS — tcp:// ilki
        assertEquals("tcp://1.1.1.1:53", j.getJSONObject("dns").getJSONArray("servers").getString(0))
        assertFalse(Cfg.full(link, true).contains("dnsck"))
    }

    private fun fake(answers: Int): DatagramSocket {
        val so = DatagramSocket(0)
        thread {
            runCatching {
                val b = ByteArray(512); val p = DatagramPacket(b, b.size); so.receive(p)
                val r = b.copyOf(p.length); r[2] = (0x81).toByte(); r[3] = 0x80.toByte(); r[7] = answers.toByte()
                so.send(DatagramPacket(r, r.size, p.socketAddress))
            }
        }
        return so
    }

    @Test fun okWhenAnswered() { val s = fake(1); assertTrue(Dns.ok(s.localPort, 2000)); s.close() }
    @Test fun badWhenNoAnswer() { val s = fake(0); assertFalse(Dns.ok(s.localPort, 1500)); s.close() }
    @Test fun badWhenSilent() { val s = DatagramSocket(0); assertFalse(Dns.ok(s.localPort, 800)); s.close() }
    @Test fun queryShape() { val q = Dns.query("www.google.com", 0x1234); assertEquals(0x12, q[0].toInt()); assertEquals(12 + 16 + 4, q.size) }
}
