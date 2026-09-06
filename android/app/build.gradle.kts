plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "uk.autoskipper.controls"
    compileSdk = 36

    defaultConfig {
        applicationId = "uk.autoskipper.controls"
        minSdk = 26
        targetSdk = 36
        versionCode = 9
        versionName = "0.4.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    // For BuildConfig.VERSION_NAME on the setup screen. Off by default since AGP 8.
    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.media:media:1.7.0")
    implementation("androidx.security:security-crypto:1.0.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")

    // Only LyricsTiming is covered: it decides which line is on screen and when
    // the next one is due, and it is the one piece that cannot be checked by
    // running the app — a wrong boundary looks like a lag, not like a failure.
    testImplementation("junit:junit:4.13.2")
}
