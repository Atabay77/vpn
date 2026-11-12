package tm.yol.vpn

import android.content.Context
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.security.KeyFactory
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.MessageDigest
import java.security.spec.ECGenParameterSpec
import java.security.spec.PKCS8EncodedKeySpec
import java.security.spec.X509EncodedKeySpec
import java.util.concurrent.ConcurrentHashMap
import javax.crypto.KeyAgreement

/**
 * 1.16: profil, Global chat suratlary we hususy habarlar (Firestore arkaly, VPN-siz).
 *
 * Profil: p/<telefon> — kiçi surat, nik we hususy habar açary (hemmeler okaýar); q/<telefon> — uly surat we fon (profil açylanda).
 * Hususy habar: her telefonyň öz EC açary bar; iki telefonyň umumy syry ECDH bilen hasaplanýar we
 * habarlar şol syr bilen şifrlenýär — diňe iki tarap okap bilýär (bot hem, başga ulanyjy hem däl).
 * x/<otag>/i — otagyň habarlary, r/<telefon>/i — «saňa täze adam ýazdy» bildirişi.
 */
object Chat {
    private fun sha(b: ByteArray) = MessageDigest.getInstance("SHA-256").digest(b)
    private fun hex(b: ByteArray) = b.joinToString("") { "%02x".format(it) }
    private fun b64(b: ByteArray) = Base64.encodeToString(b, Base64.NO_WRAP)
    private fun unb64(s: String) = Base64.decode(s, Base64.DEFAULT)
    private fun p(c: Context) = c.getSharedPreferences("dm", 0)
    private val DEV = Regex("^[0-9a-f]{12}$")

    // ---- açarlar ----
    @Volatile private var kp: KeyPair? = null
    @Synchronized fun keys(c: Context): KeyPair {
        kp?.let { return it }
        val pr = p(c); val kf = KeyFactory.getInstance("EC")
        val got = runCatching {
            KeyPair(kf.generatePublic(X509EncodedKeySpec(unb64(pr.getString("pub", null)!!))), kf.generatePrivate(PKCS8EncodedKeySpec(unb64(pr.getString("priv", null)!!))))
        }.getOrNull() ?: KeyPairGenerator.getInstance("EC").run { initialize(ECGenParameterSpec("secp256r1")); generateKeyPair() }.also {
            pr.edit().putString("pub", b64(it.public.encoded)).putString("priv", b64(it.private.encoded)).apply()
        }
        kp = got; return got
    }
    fun pub(c: Context): String = b64(keys(c).public.encoded)

    private val secrets = ConcurrentHashMap<String, String>()
    /** Iki telefonyň umumy syry (hex) — diňe men we ol hasaplap bilýäris. */
    fun secret(c: Context, peerPub: String): String? = secrets[peerPub] ?: runCatching {
        val pk = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(unb64(peerPub)))
        val ka = KeyAgreement.getInstance("ECDH"); ka.init(keys(c).private); ka.doPhase(pk, true)
        hex(sha(("tvdm|").toByteArray() + ka.generateSecret()))
    }.getOrNull()?.also { secrets[peerPub] = it }

    fun room(a: String, b: String): String = hex(sha(("tvroom|" + minOf(a, b) + "|" + maxOf(a, b)).toByteArray())).take(24)

    // ---- otaglar (telefonda): {otag: {p: telefon, k: açar, n: nik, st: out|in|acc|blk, t: soňky wagt}} ----
    @Synchronized fun rooms(c: Context): JSONObject = runCatching { JSONObject(p(c).getString("rooms", "{}")!!) }.getOrDefault(JSONObject())
    @Synchronized private fun upd(c: Context, room: String, f: (JSONObject) -> Unit) {
        val all = rooms(c); val r = all.optJSONObject(room) ?: JSONObject(); f(r); all.put(room, r)
        p(c).edit().putString("rooms", all.toString()).apply()
    }
    fun list(c: Context): JSONArray { val a = JSONArray(); val all = rooms(c); all.keys().forEach { a.put(all.getJSONObject(it).put("room", it)) }; return a }

    /** Ýagdaý: acc (kabul), blk (engelle), in (täzeden garaşylýar), del (sanawdan aýyr). */
    fun setSt(c: Context, peer: String, st: String) {
        if (!DEV.matches(peer)) return
        val room = room(Msg.dev(c), peer)
        if (st == "del") { synchronized(this) { val all = rooms(c); all.remove(room); p(c).edit().putString("rooms", all.toString()).apply() }; return }
        upd(c, room) { it.put("p", peer).put("st", st) }
        if (st == "acc") send(c, peer, JSONObject().put("sys", "acc"), null)
    }

    /** Garşydaşyň açary (p/<telefon>); öňküden üýtgän bolsa bildiriş. */
    private fun peerKey(c: Context, peer: String, room: String): String? {
        val k = Fs.get("p/$peer")?.first?.let { Msg.dec(it) }?.let { runCatching { JSONObject(it).optString("k") }.getOrNull() }?.takeIf { it.length > 40 }
        val old = rooms(c).optJSONObject(room)?.optString("k").orEmpty()
        if (k != null && old.isNotEmpty() && old != k) Msg.events.add(JSONObject().put("k", "dmkey").put("peer", peer))
        if (k != null) upd(c, room) { it.put("k", k) }
        return k ?: old.ifEmpty { null }
    }

    /** Habar iberýär: {x: tekst} / {ph: surat} / {st: stiker} / {sys: "acc"}. nick — öz nigim (täze otagda garşydaşa bildiriş üçin). */
    fun send(c: Context, peer: String, j: JSONObject, nick: String?) {
        if (!DEV.matches(peer) || !Fs.on()) { Msg.events.add(JSONObject().put("k", "dmerr").put("peer", peer).put("why", "fs")); return }
        val me = Msg.dev(c); val room = room(me, peer)
        Thread {
            val ok = runCatching {
                val k = peerKey(c, peer, room) ?: run { Msg.events.add(JSONObject().put("k", "dmerr").put("peer", peer).put("why", "nokey")); return@Thread }
                val sec = secret(c, k) ?: return@Thread
                val r = rooms(c).optJSONObject(room)
                if (r == null || r.optString("st").isEmpty()) upd(c, room) { it.put("p", peer).put("st", "out") }
                j.put("f", me).put("ts", System.currentTimeMillis() / 1000)
                val w = Fs.write("x/$room/i/" + Fs.newId(), Msg.encK("dm|$sec", j.toString()))
                // garşydaşa bildiriş: ilkinji habarda ýa-da 6 sagatdan soň
                val rq = rooms(c).optJSONObject(room)?.optLong("rq") ?: 0L
                if (w && j.optString("sys").isEmpty() && System.currentTimeMillis() - rq > 6 * 3600_000L) {
                    Msg.enc(JSONObject().put("f", me).put("n", (nick ?: "").take(32)).toString())?.let { if (Fs.write("r/$peer/i/" + Fs.newId(), it)) upd(c, room) { r2 -> r2.put("rq", System.currentTimeMillis()) } }
                }
                w
            }.getOrDefault(false)
            if (!ok) Msg.events.add(JSONObject().put("k", "dmerr").put("peer", peer).put("why", "send"))
            else pollRoom(c, room, false)
        }.start()
    }

    /** Otagy doly açmak (soňky 120 habar). */
    fun open(c: Context, peer: String) {
        if (!DEV.matches(peer)) return
        val room = room(Msg.dev(c), peer)
        Thread { runCatching { pollRoom(c, room, true, peer) } }.start()
    }

    @Volatile var watch: String? = null   // açyk otagyň garşydaşy

    private fun pollRoom(c: Context, room: String, full: Boolean, peer0: String? = null) {
        if (!Fs.on()) return
        val r = rooms(c).optJSONObject(room)
        val peer = peer0 ?: r?.optString("p")?.takeIf { DEV.matches(it) } ?: return
        if (r?.optString("st") == "blk" && !full) return
        val k = (if (full || r?.optString("k").isNullOrEmpty()) peerKey(c, peer, room) else r?.optString("k")) ?: return
        val sec = secret(c, k) ?: return
        val got = (if (full) Fs.query("x/$room", "i", null, 120, desc = true)?.reversed() else Fs.query("x/$room", "i", r?.optString("t"), 60)) ?: return
        val me = Msg.dev(c); val out = JSONArray(); var last = r?.optString("t").orEmpty()
        for ((id, b, t) in got) {
            if (t > last) last = t
            val o = Msg.decK("dm|$sec", b)?.let { runCatching { JSONObject(it) }.getOrNull() } ?: continue
            val f = o.optString("f"); if (f != me && f != peer) continue
            if (o.optString("sys") == "acc" && f == peer && rooms(c).optJSONObject(room)?.optString("st") == "out") upd(c, room) { it.put("st", "acc") }
            out.put(JSONObject().put("id", id).put("t", Fs.sec(t)).put("f", f).put("x", o.optString("x").take(2000)).put("ph", o.optString("ph")).put("st", o.optString("st").take(16)).put("sys", o.optString("sys"))
                .put("rp", o.optJSONObject("rp")?.let { rp(it) } ?: JSONObject.NULL))
        }
        if (last.isNotEmpty()) upd(c, room) { it.put("t", last).put("p", peer) }
        if (full || out.length() > 0) Msg.events.add(JSONObject().put("k", "dm").put("peer", peer).put("room", room).put("full", full).put("list", out)
            .put("st", rooms(c).optJSONObject(room)?.optString("st") ?: ""))
    }

    private var rAt = 0L; private var allAt = 0L
    /** Msg işçisinden: bildirişler we otaglar. */
    fun poll(c: Context, visible: Boolean, dmPage: Boolean) {
        if (!Fs.on() || !visible) return
        val now = System.currentTimeMillis()
        watch?.let { w -> runCatching { pollRoom(c, room(Msg.dev(c), w), false, w) } }
        if (now - rAt > (if (dmPage) 8_000L else 30_000L)) {
            rAt = now
            runCatching {
                val pr = p(c); val me = Msg.dev(c)
                val got = Fs.query("r/$me", "i", pr.getString("rIn", null), 30) ?: return@runCatching
                for ((_, b, t) in got) {
                    pr.edit().putString("rIn", t).apply()
                    val o = Msg.dec(b)?.let { runCatching { JSONObject(it) }.getOrNull() } ?: continue
                    val f = o.optString("f"); if (!DEV.matches(f) || f == me) continue
                    val room = room(me, f); val cur = rooms(c).optJSONObject(room)
                    if (cur?.optString("st") == "blk") continue
                    upd(c, room) { it.put("p", f).put("n", o.optString("n").take(32)); if (it.optString("st").isEmpty()) it.put("st", "in") }
                    Msg.events.add(JSONObject().put("k", "dmreq").put("peer", f).put("n", o.optString("n").take(32)))
                    runCatching { pollRoom(c, room, false, f) }
                }
            }
        }
        if (now - allAt > (if (dmPage) 10_000L else 60_000L)) {
            allAt = now
            val all = rooms(c)
            all.keys().forEach { room -> if (all.getJSONObject(room).optString("p") != watch) runCatching { pollRoom(c, room, false) } }
        }
    }

    // ---- profil ----
    /** j: {th: kiçi surat, big: uly surat, bg: fon, n: nik}. */
    fun profile(c: Context, j: JSONObject) {
        if (!Fs.on() && Sub.relay.isEmpty()) return
        val d = Msg.dev(c); val v = System.currentTimeMillis() / 1000
        Thread {
            val small = JSONObject().put("ph", j.optString("th").take(60_000)).put("n", j.optString("n").take(32)).put("k", pub(c)).put("v", v)
            val ok1 = Msg.enc(small.toString())?.let { if (Fs.on()) Fs.write("p/$d", it, create = false) else false } ?: false
            val big = JSONObject().put("ph", j.optString("big").take(200_000)).put("bg", j.optString("bg").take(200_000)).put("v", v)
            val ok2 = !Fs.on() || (Msg.enc(big.toString())?.let { Fs.write("q/$d", it, create = false) } ?: false)
            if (!ok1) Msg.events.add(JSONObject().put("k", "phfail"))
            else if (!ok2) Msg.events.add(JSONObject().put("k", "phretry"))   // uly surat/fon (Firestore düzgüni heniz täzelenmedik bolsa): sessiz, soň gaýtadan
        }.start()
    }

    /** Başga adamyň doly profili (uly surat + fon). */
    fun prof(dev: String) {
        if (!DEV.matches(dev) || !Fs.on()) return
        Thread {
            val s = Fs.get("p/$dev")?.first?.let { Msg.dec(it) }?.let { runCatching { JSONObject(it) }.getOrNull() }
            val b = Fs.get("q/$dev")?.first?.let { Msg.dec(it) }?.let { runCatching { JSONObject(it) }.getOrNull() }
            Msg.events.add(JSONObject().put("k", "prof").put("dev", dev).put("th", s?.optString("ph").orEmpty()).put("n", s?.optString("n").orEmpty())
                .put("ph", b?.optString("ph").orEmpty()).put("bg", b?.optString("bg").orEmpty()).put("dm", s?.optString("k").orEmpty().isNotEmpty()))
        }.start()
    }

    /** Alynty: kime jogap (gysga). */
    fun rp(j: JSONObject): JSONObject = JSONObject().put("i", j.optString("i").take(40)).put("n", j.optString("n").take(32)).put("t", j.optString("t").take(90))

    // ---- Global chat: surat / stiker ----
    fun gsend(c: Context, j: JSONObject) {
        val o = JSONObject().put("i", Msg.dev(c)).put("n", j.optString("n").take(32)).put("t", j.optString("t").take(600))
        j.optString("st").takeIf { it.isNotEmpty() }?.let { o.put("st", it.take(16)) }
        j.optJSONObject("rp")?.let { o.put("rp", rp(it)) }
        if (!Fs.on()) { if (j.optString("t").isNotBlank()) Msg.gsend(c, j.optString("n"), j.optString("t")) else Msg.events.add(JSONObject().put("k", "gfail").put("why", "srv")); return }   // köne ýol (VPS / ntfy)
        Thread {
            var ok = true
            val ph = j.optString("ph")
            if (ok && ph.isNotEmpty()) {
                val pid = Fs.newId()
                ok = ph.length <= 110_000 && (Msg.enc(JSONObject().put("ph", ph).toString())?.let { Fs.write("gi/$pid", it) } ?: false)
                if (ok) o.put("pi", pid)
            }
            if (ok) ok = Msg.enc(o.toString())?.let { Fs.write("g/" + Fs.newId(), it) } ?: false
            Msg.events.add(if (ok) JSONObject().put("k", "gok") else JSONObject().put("k", "gfail").put("why", if (State.online(c)) "srv" else "net"))
            if (ok) Msg.kick()
        }.start()
    }

    /** Global chat suraty ýa-da habaryň suraty (n/<id>). */
    fun img(kind: String, id: String) {
        if (!Regex("^[\\w-]{4,40}$").matches(id) || !Fs.on()) return
        val coll = if (kind == "n") "n" else "gi"
        Thread {
            val d = Fs.get("$coll/$id")?.first?.let { Msg.dec(it) }?.let { runCatching { JSONObject(it).optString("ph") }.getOrNull() } ?: ""
            Msg.events.add(JSONObject().put("k", "img").put("kind", kind).put("id", id).put("d", d))
        }.start()
    }
}
