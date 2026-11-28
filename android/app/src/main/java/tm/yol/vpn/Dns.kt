package tm.yol.vpn

import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress

/** 1.47.31: ýönekeý DNS barlagy (UDP, A ýazgysy) — VPN-iň DNS ýoly işleýärmi. */
object Dns {
    fun query(name: String, id: Int): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        out.write(id shr 8); out.write(id and 0xff); out.write(0x01); out.write(0x00)   // RD
        out.write(0); out.write(1); repeat(6) { out.write(0) }   // 1 sorag
        name.split('.').forEach { l -> out.write(l.length); out.write(l.toByteArray()) }
        out.write(0); out.write(0); out.write(1); out.write(0); out.write(1)   // A, IN
        return out.toByteArray()
    }

    /** Jogapda iň az bir A ýazgysy barmy (RCODE 0, ANCOUNT > 0). */
    fun answered(b: ByteArray, n: Int, id: Int): Boolean =
        n >= 12 && ((b[0].toInt() and 0xff) shl 8 or (b[1].toInt() and 0xff)) == id && (b[2].toInt() and 0x80) != 0 && (b[3].toInt() and 0x0f) == 0 &&
            ((b[6].toInt() and 0xff) shl 8 or (b[7].toInt() and 0xff)) > 0

    fun ok(port: Int, timeoutMs: Int, name: String = "www.google.com"): Boolean = runCatching {
        DatagramSocket().use { so ->
            so.soTimeout = timeoutMs
            val id = (System.nanoTime() and 0xffff).toInt()
            val q = query(name, id)
            so.send(DatagramPacket(q, q.size, InetAddress.getByName("127.0.0.1"), port))
            val buf = ByteArray(1500); val p = DatagramPacket(buf, buf.size)
            val end = System.currentTimeMillis() + timeoutMs
            while (System.currentTimeMillis() < end) {
                so.receive(p)
                if (answered(buf, p.length, id)) return@use true
            }
            false
        }
    }.getOrDefault(false)
}
