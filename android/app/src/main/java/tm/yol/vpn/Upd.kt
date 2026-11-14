package tm.yol.vpn

import android.app.DownloadManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Build
import android.os.Environment
import java.io.File

/**
 * Yeni sürüm: Android'in indirme yöneticisiyle arka planda iner (uygulama kapansa da sürer),
 * inen dosya saklanır (tekrar indirilmez), sistemin kendi yükleyicisiyle kurulur.
 * İndirme sürerken VPN açılamaz.
 */
object Upd {
    private fun abi() = if (Build.SUPPORTED_ABIS.any { it == "arm64-v8a" }) "64" else "32"
    private fun p(ctx: Context) = ctx.getSharedPreferences("p", 0)

    /** Bu telefona uygun, kuruludan yeni sürüm: (sürüm, Drive dosyası) ya da null. */
    fun available(cur: String): Pair<String, String>? {
        val u = listOfNotNull(Sub.upd[abi()], Sub.upd["all"]).reduceOrNull { x, y -> if (newer(y.first, x.first)) y else x } ?: return null
        return if (newer(u.first, cur)) u else null
    }

    fun newer(a: String, b: String): Boolean {
        val x = a.split('.').map { it.toIntOrNull() ?: 0 }; val y = b.split('.').map { it.toIntOrNull() ?: 0 }
        for (i in 0 until maxOf(x.size, y.size)) {
            val d = x.getOrElse(i) { 0 } - y.getOrElse(i) { 0 }
            if (d != 0) return d > 0
        }
        return false
    }

    private fun file(ctx: Context, ver: String) = File(ctx.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), "TurkmenVPN-$ver.apk")
    private fun part(ctx: Context, ver: String) = File(ctx.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), "TurkmenVPN-$ver.part")

    // 1.14.5: programmanyň özi ýükleýär (Android-yň «ýükleme dolandyryjysy» VPN içinden haýal geçýär, käbir telefonda 0%-da galýar).
    // Programma VPN-den daşarda, şonuň üçin googleapis.com-a göni we çalt barýar; kesilse galan ýerinden dowam edýär.
    @Volatile private var th: Thread? = null
    @Volatile private var st = Info(DownloadManager.STATUS_PENDING, 0, 0, 0)

    /** Ýükleme dowam edýärmi (VPN bu sırada açılmaz). */
    fun busy(ctx: Context): Boolean = th?.isAlive == true

    class Info(val status: Int, val reason: Int, val done: Long, val total: Long) {
        val pct get() = if (total > 0) (done * 100 / total).toInt() else 0
    }

    /** Häzirki ýagdaý: ýüklenýär / ýüklendi / bolmady ýa-da null (hiç zat ýok). */
    fun query(ctx: Context): Info? {
        if (busy(ctx)) return st
        val v = p(ctx).getString("dlv", null) ?: return null
        if (ready(ctx, v)) { val f = file(ctx, v); return Info(DownloadManager.STATUS_SUCCESSFUL, 0, f.length(), f.length()) }
        return if (st.status == DownloadManager.STATUS_FAILED) st else null
    }

    /** Köne/başga wersiýanyň faýllary pozulýar (gurnalan wersiýadan täze bolmadyk ýa-da garaşylmaýan). */
    fun clean(ctx: Context, cur: String, want: String? = null) {
        val dir = ctx.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: return
        dir.listFiles()?.forEach { f ->
            val v = Regex("^TurkmenVPN-(.+)\\.(apk|part)$").find(f.name)?.groupValues?.get(1) ?: return@forEach
            if (!(newer(v, cur) && (want == null || want == v))) f.delete()
        }
        val v = p(ctx).getString("dlv", null)
        if (v != null && !(newer(v, cur) && (want == null || want == v))) p(ctx).edit().remove("dlv").remove("dlok").remove("dl").apply()
        // köne wersiýalaryň Android ýüklemesi galan bolsa
        val id = p(ctx).getLong("dl", -1); if (id >= 0) { runCatching { ctx.getSystemService(DownloadManager::class.java).remove(id) }; p(ctx).edit().remove("dl").apply() }
    }

    /** Bu wersiýa doly ýüklendimi. */
    fun ready(ctx: Context, ver: String): Boolean {
        val f = file(ctx, ver)
        return p(ctx).getString("dlv", null) == ver && p(ctx).getLong("dlok", -1) == f.length() && f.length() > 100_000
    }

    /** Faýl ýüklenen bolsa gurýar, ýogsa ýüklemäge başlaýar. Dönüş: gurnamak penjiresi açyldymy. */
    fun start(ctx: Context, ver: String, fid: String): Boolean {
        if (ready(ctx, ver)) { install(ctx, ver); return true }
        if (busy(ctx)) return false
        val app = ctx.applicationContext
        p(app).edit().putString("dlv", ver).remove("dlok").putLong("dlAt", System.currentTimeMillis()).apply()
        st = Info(DownloadManager.STATUS_PENDING, 0, 0, 0)
        th = Thread({ download(app, ver, fid) }, "upd").apply { isDaemon = true; start() }
        return false
    }

    private fun download(ctx: Context, ver: String, fid: String) {
        val tmp = part(ctx, ver); val out = file(ctx, ver)
        var lastErr = 0
        for (attempt in 0 until 6) {
            val r = runCatching {
                val have = if (tmp.exists()) tmp.length() else 0L
                val c = java.net.URL(Sub.fileUrl(fid)).openConnection() as java.net.HttpURLConnection
                c.connectTimeout = 15_000; c.readTimeout = 30_000
                if (have > 0) c.setRequestProperty("Range", "bytes=$have-")
                val code = c.responseCode
                if (code != 200 && code != 206) { lastErr = code; c.disconnect(); return@runCatching false }
                val append = code == 206 && have > 0
                val total = (if (append) have else 0L) + c.contentLengthLong.coerceAtLeast(0)
                var done = if (append) have else 0L
                st = Info(DownloadManager.STATUS_RUNNING, 0, done, total)
                c.inputStream.use { i -> java.io.FileOutputStream(tmp, append).use { o ->
                    val buf = ByteArray(64 * 1024)
                    while (true) { val n = i.read(buf); if (n < 0) break; o.write(buf, 0, n); done += n; st = Info(DownloadManager.STATUS_RUNNING, 0, done, total) }
                } }
                c.disconnect()
                if (total > 0 && done < total) return@runCatching false
                out.delete(); tmp.renameTo(out)
                p(ctx).edit().putLong("dlok", out.length()).apply()
                true
            }.getOrDefault(false)
            if (r) {
                st = Info(DownloadManager.STATUS_SUCCESSFUL, 0, out.length(), out.length())
                notify(ctx, t("Täze wersiýa ýüklendi. Gurnamak üçin basyň", "Новая версия загружена. Нажмите, чтобы установить", "Yeni sürüm indirildi. Kurmak için dokunun"), true)
                return
            }
            if (lastErr == 403 || lastErr == 404) break
            runCatching { Thread.sleep(3000L * (attempt + 1)) }
        }
        st = Info(DownloadManager.STATUS_FAILED, lastErr, st.done, st.total)
    }

    /**
     * Sistemiň gurujysyny açýar (bilinmeýän çeşme rugsady şol ýerde soralýar).
     * Faýl programmanyň öz bukjasyndan ApkProvider arkaly berilýär.
     */
    fun install(ctx: Context, ver: String = p(ctx).getString("dlv", "") ?: "") {
        val f = file(ctx, ver)
        if (!f.exists()) return
        val uri = Uri.parse("content://${ctx.packageName}.apk/${f.name}")
        val i = Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        runCatching { ctx.startActivity(i) }
    }

    fun onWifi(ctx: Context): Boolean = runCatching {
        val cm = ctx.getSystemService(ConnectivityManager::class.java)
        cm.getNetworkCapabilities(cm.activeNetwork)?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true
    }.getOrDefault(false)

    /** Hata durumuna göre kullanıcıya gösterilecek yazı. */
    fun errText(ctx: Context, reason: Int): String = when {
        reason == 403 -> t("2-3 minutdan soň täzeden barlaň ýa-da başga VPN işledip täzeden barlaň",
            "Повторите через 2-3 минуты или включите другой VPN и попробуйте снова",
            "2-3 dakika sonra tekrar deneyin ya da başka bir VPN açıp tekrar deneyin")
        onWifi(ctx) -> t("Internetiňiz ýuwaş işleýär. Mobil internetiňizi açyp täzelemäge synanyşyň",
            "Интернет работает медленно. Включите мобильный интернет и попробуйте обновить",
            "İnternetiniz yavaş. Mobil veriyi açıp güncellemeyi deneyin")
        else -> t("Internetiňiz pes işleýär. Wi-Fi açyp ýa-da soňrak barlaň",
            "Интернет слабый. Включите Wi-Fi или попробуйте позже",
            "İnternetiniz zayıf. Wi-Fi açın ya da daha sonra deneyin")
    }

    fun notify(ctx: Context, text: String, tapInstall: Boolean) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(NotificationChannel("u", "Täzelenme", NotificationManager.IMPORTANCE_DEFAULT))
        val open = Intent(ctx, MainActivity::class.java).setAction(if (tapInstall) Main.INSTALL else Intent.ACTION_MAIN)
        val pi = PendingIntent.getActivity(ctx, 9, open, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val b = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(ctx, "u") else Notification.Builder(ctx)
        nm.notify(2, b.setSmallIcon(R.drawable.ic_notif).setContentTitle(ctx.getString(R.string.app_name))
            .setContentText(text).setStyle(Notification.BigTextStyle().bigText(text)).setContentIntent(pi).setAutoCancel(true).build())
    }

    /** Köne wersiýalaryň Android ýüklemesi gutaranda (indi ulanylmaýar, manifestde galýar). */
    class Done : BroadcastReceiver() {
        override fun onReceive(ctx: Context, i: Intent) {}
    }
}

/** İnen APK'yı sistem yükleyicisine verir (kendi dosyalarımız, sadece okuma). */
class ApkProvider : android.content.ContentProvider() {
    override fun onCreate() = true
    override fun openFile(uri: Uri, mode: String): android.os.ParcelFileDescriptor? {
        val ctx = context ?: return null
        val name = uri.lastPathSegment ?: return null
        if (name.contains("/") || !name.endsWith(".apk")) return null
        val f = File(ctx.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), name)
        return android.os.ParcelFileDescriptor.open(f, android.os.ParcelFileDescriptor.MODE_READ_ONLY)
    }
    override fun getType(uri: Uri) = "application/vnd.android.package-archive"
    override fun query(u: Uri, p: Array<String>?, s: String?, a: Array<String>?, o: String?): android.database.Cursor? {
        val ctx = context ?: return null
        val f = File(ctx.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), u.lastPathSegment ?: return null)
        return android.database.MatrixCursor(arrayOf(android.provider.OpenableColumns.DISPLAY_NAME, android.provider.OpenableColumns.SIZE)).apply { addRow(arrayOf(f.name, f.length())) }
    }
    override fun insert(u: Uri, v: android.content.ContentValues?) = null
    override fun delete(u: Uri, s: String?, a: Array<String>?) = 0
    override fun update(u: Uri, v: android.content.ContentValues?, s: String?, a: Array<String>?) = 0
}
