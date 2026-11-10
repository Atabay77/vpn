package tm.yol.vpn

import android.app.Activity
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.PackageInstaller
import android.os.Build
import java.net.HttpURLConnection
import java.net.URL

/** Bot yeni sürüm yayınlayınca: üstte bildirim, isteğe bağlı indirip kurma. VPN gerekmez. */
object Upd {
    private fun abi() = if (Build.SUPPORTED_ABIS.any { it == "arm64-v8a" }) "64" else "32"

    /** Bu telefona uygun, kuruluden yeni sürüm: (sürüm, Drive dosyası) ya da null. */
    fun available(cur: String): Pair<String, String>? {
        val u = Sub.upd[abi()] ?: return null
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

    /** İndirir ve Android'in kurulum onayını açar. progress: 0..100 (iş parçacığında çağrılır). */
    fun install(act: Activity, fid: String, progress: (Int) -> Unit) {
        val c = URL(Sub.fileUrl(fid)).openConnection() as HttpURLConnection
        c.connectTimeout = 15000; c.readTimeout = 30000
        try {
            if (c.responseCode != 200) throw IllegalStateException("HTTP ${c.responseCode}")
            val total = c.contentLengthLong
            val pi = act.packageManager.packageInstaller
            val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
            val id = pi.createSession(params)
            pi.openSession(id).use { s ->
                s.openWrite("app.apk", 0, if (total > 0) total else -1).use { out ->
                    c.inputStream.use { inp ->
                        val buf = ByteArray(64 * 1024); var n: Int; var done = 0L; var last = -1
                        while (inp.read(buf).also { n = it } > 0) {
                            out.write(buf, 0, n); done += n
                            if (total > 0) { val p = (done * 100 / total).toInt(); if (p != last) { last = p; progress(p) } }
                        }
                    }
                    s.fsync(out)
                }
                val i = Intent(act, Main::class.java).setAction(Main.INSTALLED)
                val flags = PendingIntent.FLAG_UPDATE_CURRENT or (if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0)
                s.commit(PendingIntent.getActivity(act, 7, i, flags).intentSender)
            }
        } finally { c.disconnect() }
    }

    /** Kurulum sonucu Main'e gelir; kullanıcı onayı gerekiyorsa sistem ekranı açılır. */
    fun onResult(act: Activity, i: Intent): Boolean {
        if (i.action != Main.INSTALLED) return false
        when (i.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                @Suppress("DEPRECATION") val confirm = i.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
                confirm?.let { act.startActivity(it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
            }
            PackageInstaller.STATUS_SUCCESS -> {}
            else -> android.widget.Toast.makeText(act, "Täzelenmedi", android.widget.Toast.LENGTH_LONG).show()
        }
        return true
    }
}
