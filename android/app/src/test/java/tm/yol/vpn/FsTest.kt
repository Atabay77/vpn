package tm.yol.vpn

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import java.net.ServerSocket

/** Firestore REST: programyň iberýän soraglary bot bilen birmeňzeş görnüşde (fakefs.py-daky ýaly). */
@RunWith(RobolectricTestRunner::class)
class FsTest {
    @Test fun rest() {
        val got = ArrayList<Pair<String, String>>()
        val ss = ServerSocket(0)
        // kiçijik HTTP serwer: her sorag üçin bir birikme (HttpURLConnection «Connection: close» bilen)
        val th = Thread {
            while (!ss.isClosed) {
                val sk = runCatching { ss.accept() }.getOrNull() ?: break
                sk.use { c ->
                    val inp = c.getInputStream().bufferedReader(Charsets.UTF_8)
                    val first = inp.readLine() ?: return@use
                    var len = 0
                    while (true) { val l = inp.readLine() ?: break; if (l.isEmpty()) break; if (l.lowercase().startsWith("content-length:")) len = l.substringAfter(':').trim().toInt() }
                    val buf = CharArray(len); var n = 0; while (n < len) { val r = inp.read(buf, n, len - n); if (r < 0) break; n += r }
                    val uri = first.split(" ")[1]; synchronized(got) { got.add(uri to String(buf, 0, n)) }
                    val path = uri.substringBefore('?')
                    val out = when {
                        path.endsWith(":commit") -> "{\"commitTime\":\"2026-11-11T10:00:00Z\"}"
                        path.endsWith(":runQuery") -> "[{\"document\":{\"name\":\"projects/proj1/databases/(default)/documents/g/abc\",\"fields\":{\"b\":{\"stringValue\":\"v1.x\"},\"t\":{\"timestampValue\":\"2026-11-11T10:00:01.123456Z\"}}},\"readTime\":\"x\"}]"
                        else -> "{\"fields\":{\"b\":{\"stringValue\":\"v1.ph\"},\"t\":{\"timestampValue\":\"2026-11-11T10:00:02Z\"}}}"
                    }.toByteArray()
                    val o = c.getOutputStream()
                    o.write("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${out.size}\r\nConnection: close\r\n\r\n".toByteArray()); o.write(out); o.flush()
                }
            }
        }.apply { isDaemon = true; start() }
        try {
            Fs.api = "http://127.0.0.1:" + ss.localPort
            Sub.meta("#tvfs: proj1 AIzaKEY000000000000000000000000000000\nss://x@1.1.1.1:1#a")
            assertTrue(Fs.on())
            assertTrue(Fs.write("m/id1", "v1.abc"))
            val (u, b) = got[0]
            assertTrue(u.startsWith("/v1/projects/proj1/databases/(default)/documents:commit?key=AIzaKEY"))
            val w = JSONObject(b).getJSONArray("writes").getJSONObject(0)
            assertEquals("projects/proj1/databases/(default)/documents/m/id1", w.getJSONObject("update").getString("name"))
            assertEquals("v1.abc", w.getJSONObject("update").getJSONObject("fields").getJSONObject("b").getString("stringValue"))
            assertEquals("REQUEST_TIME", w.getJSONArray("updateTransforms").getJSONObject(0).getString("setToServerValue"))
            assertEquals(false, w.getJSONObject("currentDocument").getBoolean("exists"))
            val q = Fs.query("d/abcdef123456", "i", "2026-11-11T09:00:00Z", 50)!!
            assertEquals(listOf(Triple("abc", "v1.x", "2026-11-11T10:00:01.123456Z")), q)
            assertTrue(got[1].first.startsWith("/v1/projects/proj1/databases/(default)/documents/d/abcdef123456:runQuery"))
            val sq = JSONObject(got[1].second).getJSONObject("structuredQuery")
            assertEquals("i", sq.getJSONArray("from").getJSONObject(0).getString("collectionId"))
            assertEquals("GREATER_THAN", sq.getJSONObject("where").getJSONObject("fieldFilter").getString("op"))
            assertEquals("v1.ph" to "2026-11-11T10:00:02Z", Fs.get("p/abcdef123456"))
            assertEquals(1794391200L, Fs.sec("2026-11-11T10:00:00.5Z"))
            Sub.meta("#tvfs: proj1 AIzaKEY000000000000000000000000000000 default\nss://x@1.1.1.1:1#a"); assertEquals("default", Sub.fsDb)
            Sub.meta("#tvfs: proj1 notakey\nss://x@1.1.1.1:1#a"); assertTrue(!Fs.on())   // ýalňyş açar kabul edilmeýär
        } finally { ss.close(); th.join(1000); Fs.api = "https://firestore.googleapis.com" }
    }
}
