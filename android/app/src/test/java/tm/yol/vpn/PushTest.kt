package tm.yol.vpn

import com.google.firebase.FirebaseApp
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment

/** 1.38: FCM sazlamalary — programma çökmesin; saklanan sazlamalar bilen Firebase başlaýar. */
@RunWith(RobolectricTestRunner::class)
class PushTest {
    @Test fun init() {
        val c = RuntimeEnvironment.getApplication()
        Push.initSaved(c)                                   // sazlama ýok — hiç zat etmeýär, çökmeýär
        assertTrue(FirebaseApp.getApps(c).isEmpty())
        Sub.meta("#tvfs: true-oarlock-494218-n7 AIzaSyDUMMYdummyDUMMYdummyDUMMYdummy12\n#tvfcm: 1:351476140662:android:145cad3e7702f27f9a2d57")
        Push.init(c)                                        // abuna faýlyndan: başlaýar, sazlamalar saklanýar
        assertEquals(1, FirebaseApp.getApps(c).size)
        assertEquals("351476140662", FirebaseApp.getInstance().options.gcmSenderId)
        val p = c.getSharedPreferences("p", 0)
        assertEquals("1:351476140662:android:145cad3e7702f27f9a2d57", p.getString("fcmApp", ""))
        assertFalse(Push.ok())                              // entek bildiriş gelmedi — barlaglar seýrekleşmeýär
        Push.onData(c, "hi")
        Push.ready = true
        assertTrue(Push.ok())                               // bildiriş geldi — indi seýrek barlag
        Sub.meta("")
    }
}
