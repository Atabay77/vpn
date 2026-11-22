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
    secDir.resolve("sec_data.h").writeText(
        "static volatile const unsigned char SK[] = {${arr(key)}};\n" +
        "static volatile const unsigned char SD[] = {${if (enc.isEmpty()) "0" else arr(enc)}};\n" +
        "#define SN ${enc.size}\n"
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
        versionCode = 112
        versionName = "1.47.9"
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
