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

android {
    namespace = "tm.yol.vpn"
    compileSdk = 35
    ndkVersion = "27.2.12479018"

    defaultConfig {
        applicationId = "tm.yol.vpn"
        minSdk = 24
        targetSdk = 35
        versionCode = 19
        versionName = "1.14.4"
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
