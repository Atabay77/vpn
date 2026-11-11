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

    /** İndirme sürüyor mu (VPN bu sırada açılmaz). */
    fun busy(ctx: Context): Boolean {
        val id = p(ctx).getLong("dl", -1); if (id < 0) return false
        if (Sub.upd.isNotEmpty() && p(ctx).getString("dlv", null)?.let { v -> Sub.upd.values.none { it.first == v } } == true) return false   // köne wersiýanyň ýüklemesi
        val st = query(ctx, id)
        if (st == null || st.status == DownloadManager.STATUS_FAILED || st.status == DownloadManager.STATUS_SUCCESSFUL) {
            if (st?.status != DownloadManager.STATUS_SUCCESSFUL) p(ctx).edit().remove("dl").apply()
            return false
        }
        return true
    }

    class Info(val status: Int, val reason: Int, val done: Long, val total: Long) {
        val pct get() = if (total > 0) (done * 100 / total).toInt() else 0
    }

    fun query(ctx: Context, id: Long = p(ctx).getLong("dl", -1)): Info? {
        if (id < 0) return null
        val dm = ctx.getSystemService(DownloadManager::class.java)
        return runCatching {
            dm.query(DownloadManager.Query().setFilterById(id)).use { c ->
                if (!c.moveToFirst()) return null
                Info(c.getInt(c.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS)),
                    c.getInt(c.getColumnIndexOrThrow(DownloadManager.COLUMN_REASON)),
                    c.getLong(c.getColumnIndexOrThrow(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR)),
                    c.getLong(c.getColumnIndexOrThrow(DownloadManager.COLUMN_TOTAL_SIZE_BYTES)))
            }
        }.getOrNull()
    }

    /**
     * Köne ýüklemeleri arassalar: gurnalan wersiýadan täze bolmadyk ýa-da başga wersiýanyň faýly galmasyn
     * (1.14-e çenli: köne faýl täze wersiýa ýerine gurulmaga synanyşylýardy → «Paket nädogry»).
     */
    fun clean(ctx: Context, cur: String, want: String? = null) {
        val v = p(ctx).getString("dlv", null) ?: return
        if (newer(v, cur) && (want == null || want == v)) return
        val id = p(ctx).getLong("dl", -1)
        if (id >= 0) runCatching { ctx.getSystemService(DownloadManager::class.java).remove(id) }
        runCatching { file(ctx, v).delete() }
        p(ctx).edit().remove("dl").remove("dlv").apply()
    }

    /** Bu sürüm daha önce eksiksiz indi mi (dosya hâlâ yerinde mi). */
    fun ready(ctx: Context, ver: String): Boolean {
        if (p(ctx).getString("dlv", null) != ver) return false
        val q = query(ctx) ?: return false
        if (q.status != DownloadManager.STATUS_SUCCESSFUL || q.done <= 0 || (q.total > 0 && q.done < q.total)) return false
        val dm = ctx.getSystemService(DownloadManager::class.java)
        val u = runCatching { dm.getUriForDownloadedFile(p(ctx).getLong("dl", -1)) }.getOrNull() ?: return false
        // faýl hakykatdan bar we açylýarmy (pozulan bolsa täzeden ýüklenýär)
        return runCatching { ctx.contentResolver.openFileDescriptor(u, "r")?.use { it.statSize > 100_000 } ?: false }.getOrDefault(false)
    }

    /** Dosya zaten indiyse doğrudan kurar; yoksa indirmeyi başlatır. Dönüş: kurulum ekranı açıldı mı. */
    fun start(ctx: Context, ver: String, fid: String): Boolean {
        if (ready(ctx, ver)) { install(ctx, ver); return true }
        clean(ctx, "999", ver)   // başga wersiýanyň / bozulan faýlyň galyndysy aýrylýar
        if (busy(ctx)) return false
        val f = file(ctx, ver); f.delete()
        val dm = ctx.getSystemService(DownloadManager::class.java)
        val r = DownloadManager.Request(Uri.parse(Sub.fileUrl(fid)))
            .setTitle(ctx.getString(R.string.app_name) + " $ver")
            .setDescription(t("Täze wersiýa ýüklenýär", "Загрузка новой версии", "Yeni sürüm indiriliyor"))
            .setMimeType("application/vnd.android.package-archive")
            .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE)
            .apply {
                // Android 10+: herkese açık «Download» klasörüne (kurulmazsa dosya yöneticisinden de açılabilir)
                if (Build.VERSION.SDK_INT >= 29) setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, "TurkmenVPN-$ver.apk")
                else setDestinationUri(Uri.fromFile(f))
            }
            .setAllowedOverMetered(true).setAllowedOverRoaming(true)
        val id = dm.enqueue(r)
        p(ctx).edit().putLong("dl", id).putString("dlv", ver).putLong("dlAt", System.currentTimeMillis()).apply()
        return false
    }

    /**
     * Sistemin yükleyicisini açar (bilinmeyen kaynak izni orada istenir, dosya tekrar inmez).
     * Dosyayı sistemin indirme servisi verir: güncelleme sırasında bizim süreç kapansa da okuma yarıda kalmaz.
     */
    fun install(ctx: Context, ver: String = p(ctx).getString("dlv", "") ?: "") {
        val dm = ctx.getSystemService(DownloadManager::class.java)
        val sys = runCatching { dm.getUriForDownloadedFile(p(ctx).getLong("dl", -1)) }.getOrNull()
        val f = file(ctx, ver)
        val uri = sys ?: if (f.exists()) Uri.parse("content://${ctx.packageName}.apk/${f.name}") else return
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
        val open = Intent(ctx, Main::class.java).setAction(if (tapInstall) Main.INSTALL else Intent.ACTION_MAIN)
        val pi = PendingIntent.getActivity(ctx, 9, open, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val b = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(ctx, "u") else Notification.Builder(ctx)
        nm.notify(2, b.setSmallIcon(R.drawable.ic_notif).setContentTitle(ctx.getString(R.string.app_name))
            .setContentText(text).setStyle(Notification.BigTextStyle().bigText(text)).setContentIntent(pi).setAutoCancel(true).build())
    }

    /** İndirme bitince (uygulama kapalı olsa bile) çağrılır. */
    class Done : BroadcastReceiver() {
        override fun onReceive(ctx: Context, i: Intent) {
            Lang.init(ctx)
            val id = i.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1)
            if (id != ctx.getSharedPreferences("p", 0).getLong("dl", -2)) return
            val st = query(ctx, id) ?: return
            if (st.status == DownloadManager.STATUS_SUCCESSFUL) {
                notify(ctx, t("Täze wersiýa ýüklendi. Gurnamak üçin basyň", "Новая версия загружена. Нажмите, чтобы установить", "Yeni sürüm indirildi. Kurmak için dokunun"), true)
            } else if (st.status == DownloadManager.STATUS_FAILED) {
                ctx.getSharedPreferences("p", 0).edit().remove("dl").apply()
                notify(ctx, errText(ctx, st.reason), false)
            }
        }
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
