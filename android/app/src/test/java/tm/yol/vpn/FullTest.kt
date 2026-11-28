package tm.yol.vpn

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.ServerSocket
import kotlin.concurrent.thread

class FullTest {
    @Test fun fullConfigHasFourPortsPerServer() {
        val s = Server("🇩🇪", "G", "A", "VLESS", "vless://11111111-2222-3333-4444-555555555555@1.2.3.4:443?type=tcp&security=tls&sni=x.com#A")
        val (cfg, used) = Pinger.config(listOf(s), intArrayOf(41001, 41002, 41003, 41004), full = true)
        val j = JSONObject(cfg); val ins = j.getJSONArray("inbounds")
        assertEquals(4, ins.length()); assertEquals(41001, used[0])
        val addrs = (0 until 4).map { ins.getJSONObject(it).getJSONObject("settings").getString("address") }
        assertEquals(listOf("www.gstatic.com", "1.1.1.1", "ip-api.com", "cachefly.cachefly.net"), addrs)
        assertEquals(4, j.getJSONObject("routing").getJSONArray("rules").getJSONObject(0).getJSONArray("inboundTag").length())
    }

    private fun httpServer(body: ByteArray, reqs: Int = 1): ServerSocket {
        val ss = ServerSocket(0)
        thread { runCatching { repeat(reqs) { ss.accept().use { c -> val r = c.getInputStream().bufferedReader(); while (true) { val l = r.readLine() ?: break; if (l.isEmpty()) break }
            c.getOutputStream().write("HTTP/1.1 200 OK\r\nContent-Length: ${body.size}\r\n\r\n".toByteArray() + body); c.getOutputStream().flush() } } } }
        return ss
    }

    @Test fun okNeedsDnsAndDownload() {
        assertTrue(Pinger.Full(100, true, "DE", 200).ok)
        assertFalse(Pinger.Full(100, false, "DE", 200).ok)   // DNS ýok — hiç zat açylmaýar
        assertFalse(Pinger.Full(100, true, "DE", -1).ok)    // ýüklenmeýär
        assertFalse(Pinger.Full(-1, true, "DE", 200).ok)
    }

    @Test fun tcpDnsAnswered() {
        val ss = ServerSocket(0)
        thread { ss.accept().use { c -> val inp = java.io.DataInputStream(c.getInputStream()); val n = inp.readUnsignedShort(); val q = ByteArray(n); inp.readFully(q)
            q[2] = 0x81.toByte(); q[3] = 0x80.toByte(); q[7] = 1; c.getOutputStream().write(byteArrayOf((n shr 8).toByte(), n.toByte()) + q) } }
        assertTrue(Pinger.tcpDns(ss.localPort)); ss.close()
    }
}
