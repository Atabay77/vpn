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
        }.getOrNull() ?: (stableKeys(c) ?: KeyPairGenerator.getInstance("EC").run { initialize(ECGenParameterSpec("secp256r1")); generateKeyPair() }).also {
            pr.edit().putString("pub", b64(it.public.encoded)).putString("priv", b64(it.private.encoded)).apply()
        }
        kp = got; return got
    }

    /** 1.47.31: täze gurnalanda DM açary telefonyň öz kimliginden (ANDROID_ID — diňe şu programma görýär) çykarylýar:
     *  programma pozulyp gaýtadan gurnalsa-da açar şol — köne habarlar okalýar, garşydaşlar täze açara geçmeli däl
     *  (öň täze açar döreýärdi: gelen habarlar açylmaýardy, «täze habar bar» diýip boş söhbet görünýärdi). */
    fun stableKeys(c: Context): KeyPair? = runCatching {
        val aid = android.provider.Settings.Secure.getString(c.contentResolver, android.provider.Settings.Secure.ANDROID_ID)
        if (aid.isNullOrBlank() || aid == "9774d56d682e549c") return null   // köne emulýator / näbelli
        Ec.keyPair(sha(("tvdmk|" + c.packageName + "|" + aid).toByteArray()))
    }.getOrNull()
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
    /** 1.47.29: söhbetleri öz tarapyňdan pozmak (köpüsini birden) — sanawdan aýrylýar; garşydaş täzeden ýazsa täze söhbet bolup gelýär. */
    @Synchronized fun del(c: Context, peers: List<String>) {
        val me = Msg.dev(c); val all = rooms(c)
        peers.filter { DEV.matches(it) }.forEach { all.remove(room(me, it)) }
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
                // 1.38: garşydaşyň telefonyna bot arkaly bildiriş (FCM) — ol Firestore-y ýygy barlamasyn; 20 sn-da iň köp bir gezek
                if (w && j.optString("sys").isEmpty() && !j.has("ty") && !j.has("rd") && System.currentTimeMillis() - (dmpAt[peer] ?: 0L) > 20_000L) {
                    dmpAt[peer] = System.currentTimeMillis(); Msg.send(c, JSONObject().put("k", "dmp").put("to", peer))
                }
                // garşydaşa bildiriş: ilkinji habarda ýa-da 6 sagatdan soň
                val rq = rooms(c).optJSONObject(room)?.optLong("rq") ?: 0L
                if (w && j.optString("sys").isEmpty() && !j.has("ty") && !j.has("rd") && !j.has("re") && !j.has("dl") && !j.has("ed") && System.currentTimeMillis() - rq > 6 * 3600_000L) {
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
    private val keyStale = java.util.Collections.newSetFromMap(ConcurrentHashMap<String, Boolean>())   // 1.47.31: täze haýyş geldi — garşydaşyň açaryny täzeden al

    private fun pollRoom(c: Context, room: String, full: Boolean, peer0: String? = null) {
        if (!Fs.on()) return
        val r = rooms(c).optJSONObject(room)
        val peer = peer0 ?: r?.optString("p")?.takeIf { DEV.matches(it) } ?: return
        if (r?.optString("st") == "blk" && !full) return
        var k = (if (full || r?.optString("k").isNullOrEmpty() || keyStale.remove(peer)) peerKey(c, peer, room) else r?.optString("k")) ?: return
        var sec = secret(c, k) ?: return
        val got = (if (full) Fs.query("x/$room", "i", null, 200, desc = true)?.reversed() else Fs.query("x/$room", "i", r?.optString("t"), 60)) ?: return
        val me = Msg.dev(c); val out = JSONArray(); var last = r?.optString("t").orEmpty()
        var fresh = full
        for ((id, b, t) in got) {
            var o = Msg.decK("dm|$sec", b)?.let { runCatching { JSONObject(it) }.getOrNull() }
            if (o == null && !fresh) {   // 1.47.31: açylmady — garşydaş programmasyny gaýtadan gurup açary üýtgän bolmagy mümkin: açary täzeden alyp synanyş
                fresh = true
                peerKey(c, peer, room)?.takeIf { it != k }?.let { nk -> secret(c, nk)?.let { ns -> k = nk; sec = ns; o = Msg.decK("dm|$sec", b)?.let { runCatching { JSONObject(it) }.getOrNull() } } }
            }
            if (t > last) last = t
            if (o == null) continue
            val f = o.optString("f"); if (f != me && f != peer) continue
            if (o.optString("sys") == "acc" && f == peer && rooms(c).optJSONObject(room)?.optString("st") == "out") upd(c, room) { it.put("st", "acc") }
            out.put(JSONObject().put("id", id).put("t", Fs.sec(t)).put("f", f).put("x", o.optString("x").take(2000)).put("ph", o.optString("ph")).put("st", o.optString("st").take(16)).put("sys", o.optString("sys"))
                .put("rp", o.optJSONObject("rp")?.let { rp(it) } ?: JSONObject.NULL)
                .put("re", o.optString("re").take(40)).put("e", o.optString("e").take(8)).put("off", o.optBoolean("off"))
                .put("ty", o.optInt("ty")).put("rd", o.optLong("rd")).put("dl", o.optString("dl").take(40)).put("ed", o.optString("ed").take(40)))
        }
        if (last.isNotEmpty()) upd(c, room) { it.put("t", last).put("p", peer) }
        if (full || out.length() > 0) Msg.events.add(JSONObject().put("k", "dm").put("peer", peer).put("room", room).put("full", full).put("list", out)
            .put("st", rooms(c).optJSONObject(room)?.optString("st") ?: ""))
    }

    private var rAt = 0L; private var allAt = 0L; private var wAt = 0L
    private val dmpAt = java.util.concurrent.ConcurrentHashMap<String, Long>()
    @Volatile private var pushPend = false
    /** 1.38: FCM bildirişi — täze hususy habar: ähli otaglar we haýyşlar şol bada (programma fonda bolsa-da bir gezek). */
    fun pushDm() { rAt = 0L; allAt = 0L; pushPend = true; Msg.kick() }
    /** Msg işçisinden: bildirişler we otaglar. */
    fun poll(c: Context, visible: Boolean, dmPage: Boolean) {
        val pend = pushPend; pushPend = false
        if (!Fs.on() || (!visible && !pend)) return
        val now = System.currentTimeMillis()
        val push = Push.ok() && !Sub.fast   // 1.38: bildiriş işleýär — ätiýaçlyk barlag seýrek
        val fast = Sub.fast   // 1.34: çalt rejim
        if (now - wAt > (if (fast) 1_200L else 4_000L)) { wAt = now; watch?.let { w -> runCatching { pollRoom(c, room(Msg.dev(c), w), false, w) } } }   // 1.32.1: açyk söhbet 4 sn-da bir
        if (now - rAt > (if (fast) (if (dmPage) 3_000L else 10_000L) else if (push) (if (dmPage) 30_000L else 300_000L) else if (dmPage) 8_000L else 60_000L)) {
            rAt = now
            runCatching {
                val pr = p(c); val me = Msg.dev(c)
                // 1.47.29: gelen gutusy sahypa-sahypa (öň her barlagda diňe 30 — köp habar / hekaýa görüldi bolsa täze ýazanlar sagatlap gijä galýardy)
                var pg = 0
                // 1.47.31: täze gurnalan programma — diňe soňky 2 günüň haýyşlary (öň 30 günüň ähli köne haýyşlary «täze» bolup gelýärdi)
                if (pr.getString("rIn", null) == null) pr.edit().putString("rIn", java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'.000000Z'", java.util.Locale.US)
                    .apply { timeZone = java.util.TimeZone.getTimeZone("UTC") }.format(java.util.Date(System.currentTimeMillis() - 48 * 3600_000L))).apply()
                while (pg++ < 20) {
                val got = Fs.query("r/$me", "i", pr.getString("rIn", null), 100) ?: break
                for ((_, b, t) in got) {
                    pr.edit().putString("rIn", t).apply()
                    val o = Msg.dec(b)?.let { runCatching { JSONObject(it) }.getOrNull() } ?: continue
                    val f = o.optString("f"); if (!DEV.matches(f) || f == me) continue
                    if (o.has("sv")) { Msg.events.add(JSONObject().put("k", "stv").put("sv", o.optString("sv").take(40)).put("f", f).put("n", o.optString("n").take(32)).put("t", Fs.sec(t))); continue }   // 1.39: hekaýamy gördi
                    val room = room(me, f); val cur = rooms(c).optJSONObject(room)
                    if (cur?.optString("st") == "blk") continue
                    upd(c, room) { it.put("p", f).put("n", o.optString("n").take(32)); if (it.optString("st").isEmpty()) it.put("st", "in") }
                    keyStale.add(f)
                    Msg.events.add(JSONObject().put("k", "dmreq").put("peer", f).put("n", o.optString("n").take(32)))
                    runCatching { pollRoom(c, room, false, f) }
                }
                if (got.size < 100) break
                }
            }
        }
        if (now - allAt > (if (fast) (if (dmPage) 4_000L else 20_000L) else if (push) (if (dmPage) 30_000L else 600_000L) else if (dmPage) 10_000L else 180_000L)) {
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
        j.optInt("lv").takeIf { it in 2..10 }?.let { o.put("lv", it) }   // dereje nyşany
        if (j.has("ow")) o.put("ow", if (j.optInt("ow") == 1) 1 else 0)   // 1.28: eýesi OWNER ýa-da dereje bilen görünýär
        j.optString("dl").takeIf { it.isNotEmpty() }?.let { o.put("dl", it.take(40)) }   // 1.28: öz habaryny pozmak
        j.optString("ed").takeIf { it.isNotEmpty() }?.let { o.put("ed", it.take(40)) }   // 1.28: öz habaryny üýtgetmek (täze tekst «t»-de)
        if (j.optInt("sty") == 1) o.put("sty", 1).put("vs", 1)   // 1.28: hekaýa (24 sagat); 1.39: «vs» — kim gördi ýazgysy goldanýar
        j.optString("re").takeIf { it.isNotEmpty() }?.let { o.put("re", it.take(40)).put("e", j.optString("e").take(8)).put("off", j.optBoolean("off")) }   // tepki
        if (!Fs.on() && (o.has("re") || o.has("dl") || o.has("ed") || o.has("sty"))) return   // köne ýolda tepki / pozmak / hekaýa ýok
        if (!Fs.on()) { if (j.optString("t").isNotBlank()) Msg.gsend(c, j.optString("n"), j.optString("t")) else Msg.events.add(JSONObject().put("k", "gfail").put("why", "srv")); return }   // köne ýol (VPS / ntfy)
        Thread {
            var ok = true
            val ph = j.optString("ph")
            if (ok && ph.isNotEmpty()) {
                val pid = Fs.newId()
                ok = ph.length <= 110_000 && (Msg.enc(JSONObject().put("ph", ph).toString())?.let { Fs.write("gi/$pid", it) } ?: false)
                if (ok) o.put("pi", pid)
            }
            // 1.39: gysga wideo (diňe hekaýa) — 100 KB bölekler gi/-e, sanawy «vc»
            val vd = j.optString("vd")
            if (ok && vd.isNotEmpty() && o.has("sty")) {
                val parts = vd.chunked(100_000)
                ok = parts.size <= 14
                val ids = ArrayList<String>()
                for (pt in parts) {
                    if (!ok) break
                    val id = Fs.newId()
                    ok = Msg.enc(JSONObject().put("v", pt).toString())?.let { Fs.write("gi/$id", it) } ?: false
                    ids.add(id)
                }
                if (ok) o.put("vc", ids.joinToString(","))
            }
            if (ok) ok = Msg.gPut(o)   // 1.40: VPS + Firestore
            Msg.events.add(if (ok) JSONObject().put("k", "gok") else JSONObject().put("k", "gfail").put("why", if (State.online(c)) "srv" else "net"))
            if (ok) Msg.gNow()
        }.start()
    }

    /** 1.39: hekaýanyň wideosy — bölekleri ýygnap «data:video/…» berýär. */
    fun vid(id: String, vc: String) {
        val ids = vc.split(',').filter { Regex("^[\\w-]{4,40}$").matches(it) }.take(14)
        if (ids.isEmpty() || !Fs.on()) return
        Thread {
            val sb = StringBuilder()
            for (p in ids) {
                val v = Fs.get("gi/$p")?.first?.let { Msg.dec(it) }?.let { runCatching { JSONObject(it).optString("v") }.getOrNull() }
                if (v == null) { sb.setLength(0); break }
                sb.append(v)
            }
            Msg.events.add(JSONObject().put("k", "vid").put("id", id).put("d", sb.toString()))
        }.start()
    }

    /** 1.39: hekaýany gördüm — eýesine (r/<eýesi>/i, hususy habar haýyşlarynyň gutusy) «sv» ýazgysy. */
    fun stView(c: Context, owner: String, sid: String, nick: String) {
        if (!DEV.matches(owner) || owner == Msg.dev(c) || !Regex("^[\\w-]{4,40}$").matches(sid) || !Fs.on()) return
        Thread { Msg.enc(JSONObject().put("sv", sid).put("f", Msg.dev(c)).put("n", nick.take(32)).toString())?.let { Fs.write("r/$owner/i/" + Fs.newId(), it) } }.start()
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
