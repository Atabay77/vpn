package tm.yol.vpn

import android.app.PendingIntent
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.drawable.Icon
import android.os.Build
import android.service.quicksettings.Tile as QsTile
import android.service.quicksettings.TileService

/** Bildirim panelindeki Aç/Kapat kısayolu. Açmak programı açar (bağlanırken ekranda beklenir). */
class Tile : TileService() {
    override fun onStartListening() { State.app = applicationContext; Lang.init(this); draw() }

    override fun onClick() {
        if (State.now == State.ON || State.now == State.WAIT) {
            startService(Intent(this, Svc::class.java).setAction(Svc.STOP))
            return
        }
        val i = Intent(this, Main::class.java).setAction(Main.GO).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (Build.VERSION.SDK_INT >= 34)
            startActivityAndCollapse(PendingIntent.getActivity(this, 3, i, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT))
        else @Suppress("DEPRECATION") startActivityAndCollapse(i)
    }

    private fun draw() {
        val t = qsTile ?: return
        t.state = when (State.now) { State.ON -> QsTile.STATE_ACTIVE; else -> QsTile.STATE_INACTIVE }
        t.label = getString(R.string.app_name)
        if (Build.VERSION.SDK_INT >= 29) t.subtitle = when (State.now) {
            State.ON -> t("Birikdirildi", "Подключено", "Bağlandı"); State.WAIT -> t("Birikdirilýär…", "Подключение…", "Bağlanıyor…"); else -> t("Öçük", "Выключено", "Kapalı")
        }
        t.icon = Icon.createWithResource(this, R.drawable.ic_tile)
        t.updateTile()
    }

    companion object {
        fun refresh(ctx: Context) = runCatching {
            requestListeningState(ctx, ComponentName(ctx, Tile::class.java))
        }
    }
}
