package tm.yol.vpn

import android.app.NotificationManager
import android.app.job.JobScheduler
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf

/** 1.47.21: täze wersiýa bildirişi (programma ýapyk bolsa-da — fon barlagy). */
@RunWith(RobolectricTestRunner::class)
class UpdNotifyTest {
    @Test fun notifyOncePerDay() {
        val ctx = RuntimeEnvironment.getApplication()
        val nm = ctx.getSystemService(NotificationManager::class.java)
        Sub.meta("#tvul: ${Msg.ver(ctx)} https://turkmenvpn.ru/TurkmenVPN.apk")
        Upd.notifyNew(ctx)
        assertEquals("häzirki wersiýa — bildiriş ýok", 0, shadowOf(nm).allNotifications.size)
        Sub.meta("#tvul: 99.0.0 https://turkmenvpn.ru/TurkmenVPN.apk")
        Upd.notifyNew(ctx)
        assertEquals(1, shadowOf(nm).allNotifications.size)
        assertTrue(shadowOf(shadowOf(nm).allNotifications[0]).contentText.toString().contains("99.0.0"))
        val p = ctx.getSharedPreferences("p", 0)
        assertEquals(1, p.getInt("updNn", 0))
        Upd.notifyNew(ctx); assertEquals("24 sagat içinde gaýtalanmaýar", 1, p.getInt("updNn", 0))
        p.edit().putLong("updNat", System.currentTimeMillis() - 25 * 3600_000L).apply()
        Upd.notifyNew(ctx); assertEquals("24 sagatdan soň ýene", 2, p.getInt("updNn", 0))
        p.edit().putLong("updNat", 0).putInt("updNn", 3).apply()
        Upd.notifyNew(ctx); assertEquals("iň köp 3 gezek", 3, p.getInt("updNn", 0))
        Sub.meta("#tvul: 99.0.1 https://turkmenvpn.ru/TurkmenVPN.apk")
        Upd.notifyNew(ctx); assertEquals("täze wersiýa — sanaw täzeden", 1, p.getInt("updNn", 0))
    }
    @Test fun jobScheduledOnce() {
        val ctx = RuntimeEnvironment.getApplication()
        Upd.schedule(ctx); Upd.schedule(ctx)
        val jobs = ctx.getSystemService(JobScheduler::class.java).allPendingJobs
        assertEquals(1, jobs.size); assertTrue(jobs[0].isPeriodic); assertTrue(jobs[0].isPersisted)
    }
}
