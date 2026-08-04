package uk.autoskipper.controls

import java.io.IOException
import java.util.concurrent.TimeUnit
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

/** Snapshot of GET /api/playback — only the fields the browse tree needs. */
data class PlaybackSnapshot(
    val skippingPaused: Boolean,
    val trackName: String?,
    val artist: String?,
)

sealed interface ApiResult<out T> {
    data class Ok<T>(val value: T) : ApiResult<T>

    /** Message is already user-facing: it goes straight into the STATE_ERROR text. */
    data class Err(val message: String) : ApiResult<Nothing>
}

/**
 * Blocking HTTP client for the Auto-Skipper playback API. Callers must stay off
 * the main thread (the service wraps every call in Dispatchers.IO).
 */
class ApiClient(private val baseUrl: String, private val token: String) {

    fun getPlayback(): ApiResult<PlaybackSnapshot> =
        execute(Request.Builder().url(url("/api/playback")).get()) { body ->
            val json = JSONObject(body)
            val track = json.optJSONObject("track")
            PlaybackSnapshot(
                skippingPaused = json.optBoolean("skipping_paused", false),
                trackName = track?.optString("name")?.ifBlank { null },
                artist = track?.optString("artist")?.ifBlank { null },
            )
        }

    fun checkNow(): ApiResult<Unit> = post("/api/playback/check-now") { }

    /** Returns the new skipping_paused value reported by the server. */
    fun togglePause(): ApiResult<Boolean> = post("/api/playback/toggle-pause") { body ->
        JSONObject(body).optBoolean("skipping_paused", false)
    }

    private fun <T> post(path: String, parse: (String) -> T): ApiResult<T> =
        execute(Request.Builder().url(url(path)).post(EMPTY_BODY), parse)

    private fun <T> execute(builder: Request.Builder, parse: (String) -> T): ApiResult<T> {
        val request = builder.header("Authorization", "Bearer $token").build()
        return try {
            http.newCall(request).execute().use { response ->
                val body = response.body?.string().orEmpty()
                if (response.isSuccessful) {
                    ApiResult.Ok(parse(body))
                } else {
                    ApiResult.Err(errorMessage(response.code, body))
                }
            }
        } catch (e: IOException) {
            // Covers connect/read failures and the call timeout.
            ApiResult.Err(UNREACHABLE)
        } catch (e: Exception) {
            ApiResult.Err("Unexpected response from server")
        }
    }

    /** Server errors are shown verbatim — the API already phrases them for humans. */
    private fun errorMessage(code: Int, body: String): String {
        if (code == 401) return "Token rejected — re-pair the device"
        val json = runCatching { JSONObject(body) }.getOrNull()
        val error = json?.optString("error")?.ifBlank { null }
        val detail = json?.optString("detail")?.ifBlank { null }
        return error ?: detail ?: "Server error ($code)"
    }

    private fun url(path: String): String = baseUrl + path

    companion object {
        const val UNREACHABLE = "Server unreachable"
        private const val TIMEOUT_SECONDS = 5L
        private val EMPTY_BODY = "".toRequestBody(null)

        /** One client for the process — settings changes only swap baseUrl/token. */
        private val http = OkHttpClient.Builder()
            .connectTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .readTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .writeTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .callTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .build()
    }
}
