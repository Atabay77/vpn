package tm.yol.vpn

import org.json.JSONArray
import org.json.JSONObject
import java.net.URLDecoder

/** Abonelik satırından Xray JSON ayarı üretir. */
object Cfg {
    fun dec(s: String): String = runCatching { URLDecoder.decode(s.replace("+", "%2B"), "UTF-8") }.getOrDefault(s)

    class Link(val scheme: String, val user: String, val host: String, val port: Int, val q: Map<String, String>)

    fun link(uri: String): Link {
        val noFrag = uri.substringBefore('#')
        val scheme = noFrag.substringBefore("://").lowercase()
        val rest = noFrag.substringAfter("://")
        val auth = rest.substringBefore('?').substringBefore('/')
        val query = if (rest.contains('?')) rest.substringAfter('?') else ""
        val user = if (auth.contains('@')) auth.substringBeforeLast('@') else ""
        val hp = auth.substringAfterLast('@')
        val host: String; val port: Int
        if (hp.startsWith("[")) {
            host = hp.substring(1, hp.indexOf(']'))
            port = hp.substringAfter("]:", "443").toInt()
        } else {
            host = hp.substringBeforeLast(':')
            port = hp.substringAfterLast(':', "443").toInt()
        }
        val q = query.split('&').filter { it.contains('=') }
            .associate { dec(it.substringBefore('=')) to dec(it.substringAfter('=')) }
        return Link(scheme, dec(user), host, port, q)
    }

    /** Sunucu için giden (proxy) bağlantı tanımı. */
    fun outbound(uri: String): JSONObject {
        val l = link(uri)
        val o = JSONObject().put("tag", "proxy")
        when (l.scheme) {
            "hysteria2", "hy2" -> {
                o.put("protocol", "hysteria")
                o.put("settings", JSONObject().put("version", 2).put("address", l.host).put("port", l.port))
                val tls = JSONObject().put("serverName", l.q["sni"] ?: l.host).put("alpn", JSONArray().put("h3"))
                (l.q["pinSHA256"] ?: l.q["pcs"])?.let { tls.put("pinnedPeerCertSha256", it) }
                val st = JSONObject().put("network", "hysteria").put("security", "tls")
                    .put("tlsSettings", tls)
                    .put("hysteriaSettings", JSONObject().put("version", 2).put("auth", l.user))
                l.q["fm"]?.let { st.put("finalmask", JSONObject(it)) }
                if (l.q["fm"] == null && l.q["obfs"] == "salamander") {
                    st.put("finalmask", JSONObject().put("udp", JSONArray().put(
                        JSONObject().put("type", "salamander")
                            .put("settings", JSONObject().put("password", l.q["obfs-password"] ?: "")))))
                }
                o.put("streamSettings", st)
            }
            "ss" -> {
                val raw = l.user
                val mp = if (raw.contains(':')) raw else String(
                    android.util.Base64.decode(raw.replace('-', '+').replace('_', '/'), android.util.Base64.DEFAULT),
                    Charsets.UTF_8)
                val srv = JSONObject().put("address", l.host).put("port", l.port)
                    .put("method", mp.substringBefore(':')).put("password", mp.substringAfter(':'))
                o.put("protocol", "shadowsocks")
                o.put("settings", JSONObject().put("servers", JSONArray().put(srv)))
            }
            "vless" -> {
                val user = JSONObject().put("id", l.user).put("encryption", l.q["encryption"] ?: "none")
                l.q["flow"]?.takeIf { it.isNotEmpty() }?.let { user.put("flow", it) }
                o.put("protocol", "vless")
                o.put("settings", JSONObject().put("vnext", JSONArray().put(
                    JSONObject().put("address", l.host).put("port", l.port).put("users", JSONArray().put(user)))))
                val net = l.q["type"] ?: "tcp"
                val sec = l.q["security"] ?: "none"
                val st = JSONObject().put("network", net).put("security", sec)
                when (sec) {
                    "tls" -> st.put("tlsSettings", JSONObject().put("serverName", l.q["sni"] ?: l.host)
                        .put("fingerprint", l.q["fp"] ?: "chrome").also { t ->
                            l.q["alpn"]?.let { a -> t.put("alpn", JSONArray(a.split(','))) }
                            l.q["pcs"]?.let { t.put("pinnedPeerCertSha256", it) }
                        })
                    "reality" -> st.put("realitySettings", JSONObject().put("serverName", l.q["sni"] ?: "")
                        .put("fingerprint", l.q["fp"] ?: "chrome").put("publicKey", l.q["pbk"] ?: "")
                        .put("shortId", l.q["sid"] ?: "").put("spiderX", l.q["spx"] ?: ""))
                }
                when (net) {
                    "ws" -> st.put("wsSettings", JSONObject().put("path", l.q["path"] ?: "/").put("host", l.q["host"] ?: ""))
                    "grpc" -> st.put("grpcSettings", JSONObject().put("serviceName", l.q["serviceName"] ?: ""))
                    "xhttp" -> st.put("xhttpSettings", JSONObject().put("path", l.q["path"] ?: "/")
                        .put("host", l.q["host"] ?: "").put("mode", l.q["mode"] ?: "auto"))
                    "httpupgrade" -> st.put("httpupgradeSettings", JSONObject().put("path", l.q["path"] ?: "/").put("host", l.q["host"] ?: ""))
                }
                o.put("streamSettings", st)
            }
            else -> throw IllegalArgumentException("desteklenmeyen")
        }
        return o
    }

    /** Tam ayar. tun=true ise VPN arayüzü (TUN) girişi eklenir; false ise yalnız ms ölçümü için. */
    fun full(uri: String, tun: Boolean, socks: Int = 0): String {
        val c = JSONObject()
        c.put("log", JSONObject().put("loglevel", "warning"))
        c.put("dns", JSONObject().put("servers", JSONArray().put("https://1.1.1.1/dns-query").put("https://8.8.8.8/dns-query")))
        if (tun) {
            val ins = JSONArray().put(JSONObject().put("tag", "tun").put("protocol", "tun")
                .put("settings", JSONObject().put("name", "tun0").put("mtu", 1500)))
            // programmanyň öz habarlary (bot, Global chat) üçin: diňe şu telefonyň içinden ýetip bolýar
            if (socks > 0) ins.put(JSONObject().put("tag", "loc").put("protocol", "socks").put("listen", "127.0.0.1").put("port", socks)
                .put("settings", JSONObject().put("auth", "noauth").put("udp", false)))
            c.put("inbounds", ins)
        }
        c.put("outbounds", JSONArray()
            .put(outbound(uri))
            .put(JSONObject().put("tag", "direct").put("protocol", "freedom"))
            .put(JSONObject().put("tag", "dns-out").put("protocol", "dns")))
        c.put("routing", JSONObject().put("domainStrategy", "AsIs").put("rules", JSONArray()
            .put(JSONObject().put("type", "field").put("inboundTag", JSONArray().put("tun"))
                .put("port", "53").put("outboundTag", "dns-out"))
            .put(JSONObject().put("type", "field").put("ip", JSONArray()
                .put("10.0.0.0/8").put("172.16.0.0/12").put("192.168.0.0/16").put("127.0.0.0/8")
                .put("169.254.0.0/16").put("fc00::/7").put("fe80::/10"))
                .put("outboundTag", "direct"))))
        return c.toString()
    }
}
