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
        versionCode = 8
        versionName = "1.7"
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
    // tek APK (paylaşmak için) + mimariye göre küçük APK'lar (bottan güncelleme için, 20 MB altı)
    splits { abi { isEnable = true; reset(); include("arm64-v8a", "armeabi-v7a"); isUniversalApk = true } }
}

dependencies {
    implementation(fileTree("libs") { include("*.aar", "*.jar") })
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}

tasks.register("checkSub") {
    doFirst { if (subUrl.isBlank()) throw GradleException("SUB_URL verilmedi") }
}
tasks.matching { it.name == "preReleaseBuild" }.configureEach { dependsOn("checkSub") }
