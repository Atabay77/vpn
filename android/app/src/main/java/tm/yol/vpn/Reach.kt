package tm.yol.vpn

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.telephony.TelephonyManager
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * 1.37: VPN-siz haýsy hyzmatlar açylýar? Günde bir gezek telefon (operatoryň öz ulgamyndan) dalaşgär hyzmatlary barlaýar
 * we netijäni bota iberýär. Programmanyň öz trafigi VPN tunelinden geçmeýär (addDisallowedApplication), şonuň üçin
 * VPN açyk bolsa-da barlag göni operatoryň üstünden gidýär. Şahsy maglumat iberilmeýär: diňe hyzmat → ms / ýalňyşlyk görnüşi,
 * operatoryň ady we Wi-Fi / mobil.
 */
object Reach {
    private const val EVERY = 24 * 60 * 60 * 1000L

    fun targets(): List<Pair<String, String>> {
        val p = Sub.fsProj.ifEmpty { "true-oarlock-494218-n7" }
        val l = mutableListOf(
            "fs" to "https://firestore.googleapis.com/",
            "gapis" to "https://www.googleapis.com/",
            "rtdb" to "https://$p-default-rtdb.firebaseio.com/.json",
            "rtdb_eu" to "https://$p-default-rtdb.europe-west1.firebasedatabase.app/.json",
            "fcm" to "https://fcm.googleapis.com/",
            "fb_store" to "https://firebasestorage.googleapis.com/",
            "fb_auth" to "https://identitytoolkit.googleapis.com/",
            "web_app" to "https://$p.web.app/",
            "fbapp" to "https://$p.firebaseapp.com/",
            "appspot" to "https://$p.appspot.com/",
            "gcf" to "https://us-central1-$p.cloudfunctions.net/",
            "g_script" to "https://script.google.com/",
            "g_script_uc" to "https://script.googleusercontent.com/",
            "g_sheets" to "https://sheets.googleapis.com/",
            "g_sites" to "https://sites.google.com/",
            "g_docs" to "https://docs.google.com/",
            "g_drive" to "https://drive.google.com/",
            "cf" to "https://www.cloudflare.com/cdn-cgi/trace",
            "cf_dev" to "https://developers.cloudflare.com/",
            "supabase" to "https://api.supabase.com/",
            "vercel" to "https://vercel.com/",
            "netlify" to "https://www.netlify.com/",
            "render" to "https://render.com/",
            "deno" to "https://deno.com/",
            "fly" to "https://fly.io/",
            "ya" to "https://ya.ru/",
            "ya_func" to "https://functions.yandexcloud.net/",
            "ya_store" to "https://storage.yandexcloud.net/",
            "aws_s3" to "https://s3.amazonaws.com/",
            "azure" to "https://azure.microsoft.com/",
            "gh_raw" to "https://raw.githubusercontent.com/",
            "gh_api" to "https://api.github.com/",
            "gh_pages" to "https://pages.github.com/",
            "jsdelivr" to "https://cdn.jsdelivr.net/",
            "vk" to "https://api.vk.com/",
            "telegram" to "https://api.telegram.org/",
            "ntfy" to "https://ntfy.sh/",
        )
        if (Sub.relay.isNotEmpty()) l += "relay" to Sub.relay.trimEnd('/') + "/"
        return l
    }

    /** Bir hyzmat: jogap gelse (islendik HTTP kod) — ms; gelmese ýalňyşlyk görnüşi. */
    fun probe(url: String): Any {
        val t0 = System.currentTimeMillis()
        return try {
            val c = URL(url).openConnection() as HttpURLConnection
            c.connectTimeout = 6000; c.readTimeout = 6000; c.instanceFollowRedirects = false
            c.setRequestProperty("User-Agent", "Mozilla/5.0")
            val code = c.responseCode; c.disconnect()
            if (code > 0) (System.currentTimeMillis() - t0).toInt().coerceAtLeast(1) else "err"
        } catch (e: java.net.UnknownHostException) { "dns" }
        catch (e: java.net.SocketTimeoutException) { "to" }
        catch (e: javax.net.ssl.SSLException) { "ssl" }
        catch (e: java.net.ConnectException) { "ref" }
        catch (e: java.net.SocketException) { "rst" }
        catch (e: Throwable) { "err" }
    }

    private fun net(ctx: Context): String = runCatching {
        val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        cm.allNetworks.mapNotNull { cm.getNetworkCapabilities(it) }.let { caps ->
            when {
                caps.any { it.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) } -> "wifi"
                caps.any { it.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) } -> "mobile"
                else -> "?"
            }
        }
    }.getOrDefault("?")

    private fun op(ctx: Context): String = runCatching {
        (ctx.getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager).networkOperatorName.orEmpty().trim()
    }.getOrDefault("").take(24).ifEmpty { "?" }

    /** Programma açylanda: soňky barlagdan 24 sagat geçen bolsa 60 sn soň arka fonda barlaýar we bota iberýär. */
    fun maybe(ctx: Context) {
        val c = ctx.applicationContext
        val p = c.getSharedPreferences("p", 0)
        if (System.currentTimeMillis() - p.getLong("reachAt", 0) < EVERY) return
        p.edit().putLong("reachAt", System.currentTimeMillis()).apply()
        Thread {
            runCatching {
                Thread.sleep(60_000)
                val list = targets()
                val pool = Executors.newFixedThreadPool(6)
                val fut = list.map { (k, u) -> k to pool.submit<Any> { probe(u) } }
                val r = JSONObject()
                fut.forEach { (k, f) -> r.put(k, runCatching { f.get(20, TimeUnit.SECONDS) }.getOrDefault("to")) }
                pool.shutdownNow()
                Msg.send(c, JSONObject().put("k", "reach").put("op", op(c)).put("net", net(c)).put("vpn", State.now == State.ON).put("r", r))
            }
        }.apply { isDaemon = true }.start()
    }
}
