package tm.yol.vpn

import android.content.Context
import android.os.Build
import android.os.SystemClock
import java.security.MessageDigest

/** 1.47.31: enjamyň barmak yzy — şol bir telefondaky klon programmany (Clone App, Dual Apps…) tanamak üçin. */
object Dev {
    @Volatile private var hwV: String? = null

    /** Enjam (programma däl): öndüriji, model, prošiwka, ekran, RAM, ýat. Klon programmada hem şol. */
    fun hw(c: Context): String = hwV ?: runCatching {
        val dm = c.resources.displayMetrics
        val am = c.getSystemService(android.app.ActivityManager::class.java)
        val mi = android.app.ActivityManager.MemoryInfo().also { am.getMemoryInfo(it) }
        val st = runCatching { android.os.StatFs(android.os.Environment.getDataDirectory().path).totalBytes }.getOrDefault(0L)
        val s = listOf(Build.MANUFACTURER, Build.MODEL, Build.DEVICE, Build.HARDWARE, Build.BOARD, Build.FINGERPRINT,
            "${minOf(dm.widthPixels, dm.heightPixels)}x${maxOf(dm.widthPixels, dm.heightPixels)}@${dm.densityDpi}", mi.totalMem / (64L shl 20), st / (256L shl 20)).joinToString("|")
        MessageDigest.getInstance("SHA-256").digest(("tvhw|$s").toByteArray()).joinToString("") { "%02x".format(it) }.take(16)
    }.getOrDefault("").also { hwV = it }

    /** Telefonyň açylan wagty (sekunt) — iki klon programmada birmeňzeş, başga telefonlarda däl. */
    fun boot(): Long = (System.currentTimeMillis() - SystemClock.elapsedRealtime()) / 1000

    /** Wirtual gurşaw (klon programmanyň içi): programmanyň faýllary adaty ýerde däl. */
    fun virt(c: Context): Boolean = runCatching { virtPath(c.applicationInfo.dataDir ?: "", c.applicationInfo.sourceDir ?: "", c.packageName) }.getOrDefault(false)

    fun virtPath(dataDir: String, sourceDir: String, pkg: String): Boolean {
        val q = Regex.escape(pkg)
        val dataOk = Regex("^/(data/data|data/user/\\d+|data/user_de/\\d+|mnt/expand/[^/]+/user/\\d+)/$q/?$").matches(dataDir)
        val srcOk = Regex("^/(data/app|mnt/expand/[^/]+/app)/(~~[^/]+/)?$q-[^/]+/base\\.apk$").matches(sourceDir) || sourceDir.startsWith("/system/")
        return !(dataOk && srcOk)
    }
}
