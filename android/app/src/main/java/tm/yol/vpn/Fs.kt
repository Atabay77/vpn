package tm.yol.vpn

import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/**
 * Google Firestore (REST): Türkmenistanda VPN-siz açylýar (firestore.googleapis.com).
 * Taslama we API açary abuna faýlyndan (#tvfs) gelýär; düzgünler diňe şu ýollara rugsat berýär:
 *   m/… — bota habar goýmak, g/… — Global chat, p/<telefon> — surat, d/<telefon>/i/… — telefona gelen habarlar.
 * Habarlar ýene programmanyň öz açary bilen şifrli (Msg.enc).
 */
object Fs {
    /** 1.41: #tvdb bar bolsa — Google däl, öz VPS (relay.py-daky Firestore meňzeşi, okalyş çägi ýok). */
    fun vps() = Sub.fsBase.isNotEmpty()
    fun on() = vps() || (Sub.fsProj.isNotEmpty() && Sub.fsKey.isNotEmpty())
    private fun root() = if (vps()) "projects/tv/databases/(default)/documents" else "projects/${Sub.fsProj}/databases/${Sub.fsDb}/documents"
    @Volatile var api = "https://firestore.googleapis.com"   // synag üçin üýtgedip bolýar
    private fun base() = (if (vps()) Sub.fsBase else api) + "/v1/" + root()
    private fun key() = if (vps()) "vps" else Sub.fsKey

    private fun req(method: String, url: String, body: JSONObject?, to: Int = 8000): String? = runCatching {
        val u = url + (if (url.contains('?')) "&" else "?") + "key=" + URLEncoder.encode(key(), "UTF-8")
        val c = URL(u).openConnection() as HttpURLConnection
        c.connectTimeout = to; c.readTimeout = to + 7000; c.requestMethod = method
        if (body != null) { c.doOutput = true; c.setRequestProperty("Content-Type", "application/json; charset=utf-8"); c.outputStream.use { it.write(body.toString().toByteArray()) } }
        val code = c.responseCode
        val t = (if (code in 200..299) c.inputStream else c.errorStream)?.use { it.readBytes().toString(Charsets.UTF_8) } ?: ""
        c.disconnect()
        if (code in 200..299) t else { android.util.Log.d("fs", "$code $t".take(300)); null }
    }.getOrNull()

    /** Resminama ýazmak: b + t (serweriň wagty). */
    fun write(path: String, b: String, create: Boolean = true): Boolean {
        val w = JSONObject().put("update", JSONObject().put("name", root() + "/" + path).put("fields", JSONObject().put("b", JSONObject().put("stringValue", b))))
            .put("updateTransforms", JSONArray().put(JSONObject().put("fieldPath", "t").put("setToServerValue", "REQUEST_TIME")))
        if (create) w.put("currentDocument", JSONObject().put("exists", false))
        return req("POST", base() + ":commit", JSONObject().put("writes", JSONArray().put(w))) != null
    }

    fun newId(): String = java.util.UUID.randomUUID().toString().replace("-", "").take(20)

    /** Sorag: [ (id, b, t) ] — t > after, t boýunça. Ýalňyşlykda null. */
    fun query(parent: String, coll: String, after: String?, limit: Int, desc: Boolean = false): List<Triple<String, String, String>>? {
        val q = JSONObject().put("from", JSONArray().put(JSONObject().put("collectionId", coll)))
            .put("orderBy", JSONArray().put(JSONObject().put("field", JSONObject().put("fieldPath", "t")).put("direction", if (desc) "DESCENDING" else "ASCENDING")))
            .put("limit", limit)
        if (!after.isNullOrEmpty()) q.put("where", JSONObject().put("fieldFilter", JSONObject().put("field", JSONObject().put("fieldPath", "t"))
            .put("op", "GREATER_THAN").put("value", JSONObject().put("timestampValue", after))))
        val t = req("POST", base() + (if (parent.isEmpty()) "" else "/$parent") + ":runQuery", JSONObject().put("structuredQuery", q)) ?: return null
        val out = ArrayList<Triple<String, String, String>>()
        val a = runCatching { JSONArray(t) }.getOrNull() ?: return null
        for (i in 0 until a.length()) {
            val d = a.optJSONObject(i)?.optJSONObject("document") ?: continue
            val f = d.optJSONObject("fields") ?: continue
            out.add(Triple(d.optString("name").substringAfterLast('/'), f.optJSONObject("b")?.optString("stringValue") ?: "", f.optJSONObject("t")?.optString("timestampValue") ?: ""))
        }
        return out
    }

    /** Bir resminama (surat). */
    fun get(path: String, to: Int = 8000): Pair<String, String>? {
        val t = req("GET", base() + "/" + path, null, to) ?: return null
        val f = runCatching { JSONObject(t).optJSONObject("fields") }.getOrNull() ?: return null
        return (f.optJSONObject("b")?.optString("stringValue") ?: "") to (f.optJSONObject("t")?.optString("timestampValue") ?: "")
    }

    /** Barlag: Firestore açylýarmy (ýok resminama → 404 hem «açylýar» diýmek). */
    fun ping(): Int = runCatching {
        val c = URL(base() + "/p/x?key=" + URLEncoder.encode(key(), "UTF-8")).openConnection() as HttpURLConnection
        c.connectTimeout = 8000; c.readTimeout = 8000
        val code = c.responseCode; c.disconnect(); code
    }.getOrDefault(-1)

    /** RFC3339 → sekunt. */
    fun sec(t: String): Long = runCatching {
        val f = java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", java.util.Locale.US).apply { timeZone = java.util.TimeZone.getTimeZone("UTC") }
        f.parse(t.take(19))!!.time / 1000
    }.getOrDefault(System.currentTimeMillis() / 1000)
}
