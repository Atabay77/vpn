package tm.yol.vpn
import org.junit.Test
import org.junit.Assert.*
import org.json.JSONObject
class T {
    @Test fun all() {
        val raw = """
#profile-title: vpn
#hide-settings: true
hysteria2://fakeAuth123@10.0.0.1:27001?security=tls&fm=%7B%22udp%22%3A%5B%7B%22settings%22%3A%7B%22password%22%3A%22pw%22%7D%2C%22type%22%3A%22salamander%22%7D%5D%7D&sni=a.example#🇳🇱 Netherlands · 🧡 Orange Express
hysteria2://fake%2Bx@10.0.0.2:114?sni=www.google.com&pcs=0163D314B2C4B845CDF40F5805559E87744EF640110318D93C16EF90B5C517CC&pinSHA256=0163D314B2C4B845CDF40F5805559E87744EF640110318D93C16EF90B5C517CC#🇬🇧 United Kingdom · 👑 Royal Edge
hysteria2://fakeA@10.0.0.3:136/?sni=www.google.com&insecure=0&pinSHA256=0f1850ce32644d29b1436e9d865a7a1b2d35351bb2353bf32c7c5ff4663a6c09#🇫🇮 Finland · 🦌 Lapland Runner
trojan://x@1.1.1.1:1#skip
        """.trimIndent()
        val l = Sub.parse(raw)
        assertEquals(3, l.size)
        for (s in l) {
            println("ROW ${s.flag}|${s.country}|${s.title}|${s.proto}")
            println("CFG " + Cfg.full(s.uri, true))
        }
        assertEquals("Orange Express", l[0].title)
        val o = JSONObject(Cfg.full(l[1].uri, true)).getJSONArray("outbounds").getJSONObject(0)
        assertEquals("fake+x", o.getJSONObject("streamSettings").getJSONObject("hysteriaSettings").getString("auth"))
        val ss = Cfg.outbound("ss://aes-256-gcm:p%40ss@1.2.3.4:8388#x")
        println("SS $ss")
        assertEquals("p@ss", ss.getJSONObject("settings").getJSONArray("servers").getJSONObject(0).getString("password"))
        val g = Sub.parse("ss://YWVzLTI1Ni1nY206cA==@1.2.3.4:1080#🇷🇺 Russia · 🎮 PUBG Gaming Server\nss://YWVzLTI1Ni1nY206cA==@1.2.3.4:1088#🇷🇺 Russia · 🎮 PUBG Gaming Server\nss://YWVzLTI1Ni1nY206cA==@1.2.3.5:1#🇷🇺 Russia · Moscow")
        assertEquals(listOf(true, true, false), g.map { it.game })
        assertTrue(g.all { it.ru })
        assertEquals("PUBG Gaming Server 2", g[1].title)
        assertNotEquals(g[0].key, g[1].key)
        assertFalse(l.any { it.ru || it.game })
        println("NAME " + Sub.splitName("🇷🇺 Russia · 🎮 PUBG Gaming Server") + " " + Sub.splitName("Plain"))
        println("VLESS " + Cfg.outbound("vless://uuid-1@[2001:db8::1]:443?type=tcp&security=reality&pbk=K&sid=ab&sni=x.com&fp=chrome&flow=xtls-rprx-vision#n"))
    }
}
