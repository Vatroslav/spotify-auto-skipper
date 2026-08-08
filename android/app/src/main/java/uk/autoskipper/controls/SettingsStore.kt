package uk.autoskipper.controls

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys

/**
 * Server URL and device token, encrypted at rest.
 *
 * The token grants the playback commands and nothing else (backend keeps every
 * other router session-only), but it still never lands in plain prefs.
 */
class SettingsStore(context: Context) {

    private val prefs: SharedPreferences = EncryptedSharedPreferences.create(
        PREFS_NAME,
        MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC),
        context.applicationContext,
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    var baseUrl: String
        get() = normalizeUrl(prefs.getString(KEY_URL, DEFAULT_URL) ?: DEFAULT_URL)
        set(value) {
            prefs.edit().putString(KEY_URL, normalizeUrl(value)).apply()
        }

    var token: String
        get() = (prefs.getString(KEY_TOKEN, "") ?: "").trim()
        set(value) {
            prefs.edit().putString(KEY_TOKEN, value.trim()).apply()
        }

    /** An ApiClient for the stored credentials, or null while the app is unconfigured. */
    fun apiClient(): ApiClient? {
        val url = baseUrl
        val token = token
        return if (url.isNotEmpty() && token.isNotEmpty()) ApiClient(url, token) else null
    }

    private fun normalizeUrl(value: String): String = value.trim().trimEnd('/')

    companion object {
        const val DEFAULT_URL = "https://autoskipper.uk"
        private const val PREFS_NAME = "auto_skipper_settings"
        private const val KEY_URL = "server_url"
        private const val KEY_TOKEN = "device_token"
    }
}
