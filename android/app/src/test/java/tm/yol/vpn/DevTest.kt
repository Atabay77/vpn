package tm.yol.vpn

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DevTest {
    private val p = "tm.yol.app"
    @Test fun normalInstallIsNotVirtual() {
        assertFalse(Dev.virtPath("/data/user/0/$p", "/data/app/~~Zx1A==/$p-Qw9==/base.apk", p))   // Android 11+
        assertFalse(Dev.virtPath("/data/data/$p", "/data/app/$p-1/base.apk", p))                     // Android 7–10
        assertFalse(Dev.virtPath("/data/user/999/$p", "/data/app/~~a/$p-b/base.apk", p))             // OEM «iki programma» — bot tanaýar (hw)
        assertFalse(Dev.virtPath("/mnt/expand/1234-abcd/user/0/$p", "/mnt/expand/1234-abcd/app/$p-1/base.apk", p))   // SD kart
    }
    @Test fun cloneContainerIsVirtual() {
        assertTrue(Dev.virtPath("/data/user/0/com.excelliance.multiaccounts/gameplugins/$p", "/data/user/0/com.excelliance.multiaccounts/gameplugins/$p/base.apk", p))
        assertTrue(Dev.virtPath("/data/data/com.lbe.parallel.intl/parallel_intl/0/$p", "/data/app/com.lbe.parallel.intl-1/base.apk", p))
        assertTrue(Dev.virtPath("/data/user/0/$p", "/data/user/0/com.clone.app/virtual/data/app/$p/base.apk", p))
    }
}
