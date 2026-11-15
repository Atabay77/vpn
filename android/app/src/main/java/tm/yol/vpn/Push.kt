package tm.yol.vpn

import android.content.Context
import com.google.firebase.FirebaseApp
import com.google.firebase.FirebaseOptions
import com.google.firebase.messaging.FirebaseMessaging
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import org.json.JSONObject

/**
 * 1.38: FCM — bot täze bir zat bolanda (bilet jogaby, hususy habar, admin, dereje…) telefona özi bildirýär,
 * şonda telefon Firestore-y diňe şol wagt okaýar (öň birnäçe sekuntda bir barlaýardy — Firestore-yň gündelik çägi dolýardy).
 * google-services.json ýok we açar koda ýazylmaýar: programmanyň kimligi «#tvfcm:», açar we taslama «#tvfs:» abuna setirinden.
 * Google Play hyzmatlary ýok telefonlarda (Huawei) hiç zat üýtgemeýär — öňküsi ýaly barlaýar.
 */
object Push {
    @Volatile var ready = false          // bildiriş belgisi (token) alyndy
    @Volatile var lastAt = 0L            // soňky bildiriş haçan geldi
    /** Bildirişler hakykatdan gelýär (soňky 24 sagatda biri geldi) — diňe şonda barlaglar seýrekleşýär. */
    fun ok() = ready && System.currentTimeMillis() - lastAt < 24 * 3600_000L

    @Volatile private var lastErr = ""
    private fun start(c: Context, app: String, key: String, proj: String): Boolean = try {
        if (FirebaseApp.getApps(c).isEmpty()) {
            FirebaseApp.initializeApp(c, FirebaseOptions.Builder()
                .setApplicationId(app).setApiKey(key).setProjectId(proj)
                .setGcmSenderId(app.split(':').getOrElse(1) { "" }).build())
        }
        true
    } catch (e: Throwable) { lastErr = "init: $e"; false }

    /** 1.38.1: belgi alynmasa sebäbi bota (6 sagatda iň köp bir gezek) — /fcm-de görünýär. */
    private fun fail(c: Context, why: String) {
        val p = c.getSharedPreferences("p", 0)
        if (System.currentTimeMillis() - p.getLong("fcmErrAt", 0) < 6 * 3600_000L) return
        p.edit().putLong("fcmErrAt", System.currentTimeMillis()).apply()
        val gms = runCatching { c.packageManager.getPackageInfo("com.google.android.gms", 0).versionName ?: "?" }.getOrDefault("yok")
        Msg.send(c, JSONObject().put("k", "fcmerr").put("e", why.take(300)).put("gms", gms.take(40)))
    }

    /** Programma işe başlanda: öň saklanan sazlamalar bilen (abuna faýly entek okalmadyk bolsa-da). */
    fun initSaved(ctx: Context) {
        val p = ctx.getSharedPreferences("p", 0)
        val app = p.getString("fcmApp", "") ?: ""; val key = p.getString("fcmKey", "") ?: ""; val proj = p.getString("fcmProj", "") ?: ""
        lastAt = p.getLong("pushAt", 0)
        if (app.isNotEmpty() && key.isNotEmpty() && proj.isNotEmpty()) start(ctx.applicationContext, app, key, proj)
    }

    /** Abuna faýly täzelenenden soň: Firebase-i başlat, belgini al we bota iber. */
    fun init(ctx: Context) {
        if (ready || Sub.fcmApp.isEmpty() || Sub.fsKey.isEmpty() || Sub.fsProj.isEmpty()) return
        val c = ctx.applicationContext
        c.getSharedPreferences("p", 0).edit().putString("fcmApp", Sub.fcmApp).putString("fcmKey", Sub.fsKey).putString("fcmProj", Sub.fsProj).apply()
        if (!start(c, Sub.fcmApp, Sub.fsKey, Sub.fsProj)) { fail(c, lastErr); return }
        try {
            FirebaseMessaging.getInstance().token
                .addOnSuccessListener { t -> if (!t.isNullOrEmpty()) { ready = true; report(c, t) } else fail(c, "boş belgi") }
                .addOnFailureListener { e -> fail(c, "token: $e") }
        } catch (e: Throwable) { fail(c, "token: $e") }
        Thread { runCatching { Thread.sleep(120_000); if (!ready) fail(c, "2 minutda belgi gelmedi") } }.apply { isDaemon = true }.start()
    }

    /** Täze belgi bota (diňe üýtgände). */
    fun report(c: Context, t: String) {
        val p = c.getSharedPreferences("p", 0)
        // täze belgi ýa-da 20 sagatdan bäri bildiriş gelmedik bolsa — bot synag bildirişini iberýär («hi»)
        if (p.getString("fcmTok", null) == t && System.currentTimeMillis() - p.getLong("fcmAt", 0) < 20 * 3600_000L) return
        p.edit().putString("fcmTok", t).putLong("fcmAt", System.currentTimeMillis()).apply()
        Msg.send(c, JSONObject().put("k", "fcm").put("t", t))
    }

    /** Bildiriş geldi: degişli bölümi şol bada barla. */
    fun onData(c: Context, k: String) {
        lastAt = System.currentTimeMillis(); c.getSharedPreferences("p", 0).edit().putLong("pushAt", lastAt).apply()
        Msg.start(c)
        when (k) {
            "in" -> Msg.pushIn()
            "dm" -> Chat.pushDm()
            "g" -> Msg.gNow()
            "hi" -> {}   // synag: bildirişler gelýär
            else -> { Msg.pushIn(); Chat.pushDm() }
        }
    }
}

class TvFcm : FirebaseMessagingService() {
    override fun onMessageReceived(m: RemoteMessage) { Push.onData(applicationContext, m.data["k"] ?: "") }
    override fun onNewToken(t: String) { Push.ready = true; Push.report(applicationContext, t) }
}
