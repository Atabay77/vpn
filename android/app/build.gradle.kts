import java.security.SecureRandom

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Abonelik adresi koda yazılmaz: derlemede SUB_URL ortam değişkeninden alınır,
// rastgele anahtarla XOR'lanıp yalnız native kütüphanenin içine gömülür.
val subUrl: String = System.getenv("SUB_URL") ?: (project.findProperty("SUB_URL") as String? ?: "")
val secDir = layout.buildDirectory.dir("generated/sec").get().asFile
run {
    secDir.mkdirs()
    val data = subUrl.toByteArray(Charsets.UTF_8)
    val key = ByteArray(maxOf(data.size, 1)).also { SecureRandom().nextBytes(it) }
    val enc = ByteArray(data.size) { (data[it].toInt() xor key[it].toInt()).toByte() }
    fun arr(b: ByteArray) = b.joinToString(",") { "0x%02x".format(it.toInt() and 0xff) }
    // 1.47.16: möhür (seal) — derlemeden soň seal.py kod bölegini hasaplap şu ýere ýazýar (magic → tötänleýin)
    val rnd = SecureRandom()
    val seal = ByteArray(96).also { rnd.nextBytes(it) }.also { for (i in 64 until 96) it[i] = 0 }
    secDir.resolve("sec_data.h").writeText(
        "static volatile const unsigned char SK[] = {${arr(key)}};\n" +
        "static volatile const unsigned char SD[] = {${if (enc.isEmpty()) "0" else arr(enc)}};\n" +
        "#define SN ${enc.size}\n" +
        "static volatile unsigned char SEAL[96] = {${arr(seal)}};\n"   // .data (R-X däl) — möhür özüni hash-lemesin
    )
    secDir.resolve("seal.txt").writeText(seal.copyOfRange(0, 32).joinToString("") { "%02x".format(it.toInt() and 0xff) })
    // 1.47.16: native setirler we SHA-256 hemişelikleri — her derlemede başga açar bilen XOR-lanýar (faýlda açyk görünmeýär)
    val strs = linkedMapOf(
        "S_MAPS" to "/proc/self/maps", "S_STATUS" to "/proc/self/status", "S_TRACER" to "TracerPid:", "S_BAPK" to "/base.apk",
        "S_PKG" to "tm.yol.app", "S_FRIDA" to "frida", "S_GUM" to "gum-js", "S_LINJ" to "linjector", "S_TASK" to "/proc/self/task",
        "S_COMM" to "/comm", "S_TVY" to "tvy1|", "S_TVMSG" to "tvmsg|", "S_TVMAC" to "tvmac|", "S_FILES" to "/files/",
        "S_CLS" to "tm/yol/vpn/N", "S_MU" to "u", "S_MD" to "d", "S_MS" to "s",
        "S_SIGU" to "()Ljava/lang/String;",
        "S_SIGD" to "(Landroid/content/Context;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)[B",
        "S_SIGS" to "(Landroid/content/Context;)Ljava/lang/String;",
        "S_GPCP" to "getPackageCodePath", "S_GPN" to "getPackageName", "S_GPM" to "getPackageManager",
        "S_SIGPM" to "()Landroid/content/pm/PackageManager;", "S_GPI" to "getPackageInfo",
        "S_SIGPI" to "(Ljava/lang/String;I)Landroid/content/pm/PackageInfo;", "S_SI" to "signingInfo",
        "S_SIGSI" to "Landroid/content/pm/SigningInfo;", "S_GACS" to "getApkContentsSigners",
        "S_SIGACS" to "()[Landroid/content/pm/Signature;", "S_SIGS2" to "signatures", "S_SIGARR" to "[Landroid/content/pm/Signature;",
        "S_TBA" to "toByteArray", "S_SIGTBA" to "()[B", "S_DATAAPP" to "/data/app/", "S_MNTEXP" to "/mnt/expand/",
        "S_CMDLINE" to "/proc/self/cmdline", "S_BVER" to "android/os/Build\$VERSION", "S_SDKINT" to "SDK_INT", "S_I" to "I",
        "S_SIGMAGIC" to "APK Sig Block 42"
    )
    val ss = ArrayList<Int>(); val sx = ArrayList<Int>(); val so = ArrayList<Int>(); val sl = ArrayList<Int>(); val defs = StringBuilder()
    strs.entries.forEachIndexed { i, (name, s) ->
        val b = s.toByteArray(Charsets.UTF_8); so.add(ss.size); sl.add(b.size); defs.append("#define $name $i\n")
        for (x in b) { val k = rnd.nextInt(256); ss.add((x.toInt() and 0xff) xor k); sx.add(k) }
    }
    val kk = longArrayOf(0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
        0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
        0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
        0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
        0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
        0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2)
    val hh = longArrayOf(0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19)
    fun warr(v: LongArray, m: LongArray) = v.indices.joinToString(",") { "0x%08xu".format((v[it] xor m[it]) and 0xffffffffL) }
    val km = LongArray(64) { rnd.nextInt().toLong() and 0xffffffffL }; val hm = LongArray(8) { rnd.nextInt().toLong() and 0xffffffffL }
    secDir.resolve("sec_str.h").writeText(
        defs.toString() +
        "static volatile const unsigned char SS[] = {${ss.joinToString(",")}};\n" +
        "static volatile const unsigned char SX[] = {${sx.joinToString(",")}};\n" +
        "static const unsigned short SO[] = {${so.joinToString(",")}};\n" +
        "static const unsigned short SL[] = {${sl.joinToString(",")}};\n" +
        "#define SCOUNT ${strs.size}\n" +
        "static volatile const unsigned int KX[64] = {${warr(kk, km)}};\n" +
        "static volatile const unsigned int KM[64] = {${warr(km, LongArray(64))}};\n" +
        "static volatile const unsigned int HX[8] = {${warr(hh, hm)}};\n" +
        "static volatile const unsigned int HM[8] = {${warr(hm, LongArray(8))}};\n"
    )
}

// 1.47: APK faýlynyň nyşany (ýükleme / faýl dolandyryjy) — her derlemede tötänleýin; gurlanda baş ekranda asyl nyşan (.Main ýarlygy)
val pkgIconDir = layout.buildDirectory.dir("generated/pkgicon").get().asFile
run {
    val src = file("icons").listFiles { f -> f.name.startsWith("pkg") && f.name.endsWith(".png") }?.sortedBy { it.name }.orEmpty()
    if (src.isNotEmpty()) {
        val d = pkgIconDir.resolve("mipmap-xxxhdpi"); d.mkdirs()
        src[SecureRandom().nextInt(src.size)].copyTo(d.resolve("ic_pkg.png"), overwrite = true)
    }
}

android {
    namespace = "tm.yol.vpn"
    sourceSets { getByName("main") { res.srcDir(pkgIconDir) } }
    compileSdk = 35
    ndkVersion = "27.2.12479018"

    defaultConfig {
        applicationId = "tm.yol.app"   // 1.47: täze gol (köne açar ýitdi) — täze paket: köne programmanyň üstünden däl, ýanynda gurnalýar, göçmek kody bilen
        minSdk = 24
        targetSdk = 35
        versionCode = 121
        versionName = "1.47.18"
        externalNativeBuild { cmake { arguments += "-DSEC_DIR=${secDir.absolutePath}" } }
    }

    // İmza anahtarı derlemede SIGN_KEYSTORE / SIGN_PASS ortam değişkenlerinden gelir
    val ks = System.getenv("SIGN_KEYSTORE")?.let { file(it) }?.takeIf { it.exists() }
    signingConfigs {
        if (ks != null) create("rel") {
            storeFile = ks
            storePassword = System.getenv("SIGN_PASS")
            keyAlias = System.getenv("SIGN_ALIAS") ?: "yol"
            keyPassword = System.getenv("SIGN_PASS")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (ks != null) signingConfig = signingConfigs.getByName("rel")
        }
    }

    externalNativeBuild { cmake { path = file("src/main/cpp/CMakeLists.txt") } }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    packaging { jniLibs { useLegacyPackaging = true } }
    lint { checkReleaseBuilds = false }
    testOptions { unitTests { isIncludeAndroidResources = true; all {
        it.systemProperty("shots", System.getProperty("shots") ?: "")
        it.systemProperty("robolectric.offline", "true")
        it.systemProperty("robolectric.dependency.dir", layout.buildDirectory.dir("robo").get().asFile.absolutePath)
        it.dependsOn("roboJars")
    } } }
    // tek APK (paylaşmak için) + mimariye göre küçük APK'lar (bottan güncelleme için, 20 MB altı)
    splits { abi { isEnable = true; reset(); include("arm64-v8a", "armeabi-v7a"); isUniversalApk = true } }
}

dependencies {
    implementation(fileTree("libs") { include("*.aar", "*.jar") })
    // 1.38: FCM — bot täze habar bolanda telefona özi bildirýär (Firestore-y ýygy-ýygydan barlamak gerek däl). google-services.json ýok: sazlamalar abuna faýlyndan
    implementation(platform("com.google.firebase:firebase-bom:33.7.0"))
    implementation("com.google.firebase:firebase-messaging")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    testImplementation("org.robolectric:robolectric:4.14.1")
}

tasks.register("checkSub") {
    doFirst { if (subUrl.isBlank()) throw GradleException("SUB_URL verilmedi") }
}
tasks.matching { it.name == "preReleaseBuild" }.configureEach { dependsOn("checkSub") }

// Robolectric'in Android dosyası Gradle ile indirilir (ekran görüntüsü testi için)
val robo: Configuration by configurations.creating
dependencies { robo("org.robolectric:android-all-instrumented:14-robolectric-10818077-i7"); robo("org.robolectric:android-all-instrumented:15-robolectric-12650502-i7") }
tasks.register<Copy>("roboJars") {
    from(robo); into(layout.buildDirectory.dir("robo"))
}
