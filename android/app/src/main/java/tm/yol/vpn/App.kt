package tm.yol.vpn

import android.app.Application

/** 1.38: programma işe başlanda (FCM bildirişi uklap ýatan programmany oýaranda hem) Firebase taýýar bolsun. */
class App : Application() {
    override fun onCreate() { super.onCreate(); Push.initSaved(this) }
}
