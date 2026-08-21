package uk.autoskipper.controls

import java.io.IOException
import java.net.URLEncoder
import java.util.concurrent.TimeUnit
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

/** Snapshot of GET /api/playback — only the fields the browse tree renders from. */
data class PlaybackSnapshot(
    val trackId: String?,
    val trackName: String?,
    val artist: String?,
    val skippingPaused: Boolean,
    /** null when nothing is playing or the Liked lookup failed — not the same as "not liked". */
    val isLiked: Boolean?,
    val skipExemptTrackId: String?,
    val trashConfigured: Boolean,
) {
    companion object {
        /** What the browse tree renders before the first successful poll. */
        val UNKNOWN = PlaybackSnapshot(
            trackId = null,
            trackName = null,
            artist = null,
            skippingPaused = false,
            isLiked = null,
            skipExemptTrackId = null,
            trashConfigured = false,
        )
    }
}

/** The track a command endpoint reports it acted on. */
data class TrackRef(val name: String?, val artist: String?)

/**
 * Snapshot of GET /api/lyrics.
 *
 * `lines` is empty when [linesIncluded] is false — the caller asked about a
 * track it already holds the lyrics for and the server left them out. Treating
 * that as "no lyrics" would blank the screen on every poll, so the two cases
 * must stay distinguishable.
 */
data class LyricsSnapshot(
    val state: String,
    val trackId: String?,
    val trackName: String?,
    val artist: String?,
    val lines: List<LyricLine>,
    val linesIncluded: Boolean,
    val positionMs: Long,
    val isPlaying: Boolean,
) {
    companion object {
        const val STATE_SYNCED = "synced"
        const val STATE_PLAIN_ONLY = "plain_only"
        const val STATE_INSTRUMENTAL = "instrumental"
        const val STATE_NOT_FOUND = "not_found"
        const val STATE_NOTHING_PLAYING = "nothing_playing"
    }
}

/** Result of toggle-like: the new Liked state plus the track it applies to. */
data class LikeResult(val isLiked: Boolean, val track: TrackRef)

sealed interface ApiResult<out T> {
    data class Ok<T>(val value: T) : ApiResult<T>

    /**
     * Message is already user-facing: it goes straight into the STATE_ERROR text.
     * Code is the HTTP status when there was one, so callers can special-case a
     * status without re-parsing the body (409 on a stale remove).
     */
    data class Err(val message: String, val code: Int? = null) : ApiResult<Nothing>
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
                trackId = track?.stringOrNull("id"),
                trackName = track?.stringOrNull("name"),
                artist = track?.stringOrNull("artist"),
                skippingPaused = json.optBoolean("skipping_paused", false),
                isLiked = json.booleanOrNull("is_liked"),
                skipExemptTrackId = json.stringOrNull("skip_exempt_track_id"),
                trashConfigured = json.optBoolean("trash_configured", false),
            )
        }

    /**
     * Lyrics and playback position for the current track.
     *
     * knownTrackId is what the caller already has cached; the server omits the
     * line list when it matches, so a position refresh costs a few hundred
     * bytes instead of a full lyric sheet.
     */
    fun getLyrics(knownTrackId: String?): ApiResult<LyricsSnapshot> {
        val suffix = if (knownTrackId.isNullOrEmpty()) {
            ""
        } else {
            "?known_track_id=" + URLEncoder.encode(knownTrackId, "UTF-8")
        }
        return execute(Request.Builder().url(url("/api/lyrics$suffix")).get()) { body ->
            val json = JSONObject(body)
            val track = json.optJSONObject("track")
            val linesArray = json.optJSONArray("lines")
            val lines = buildList {
                for (i in 0 until (linesArray?.length() ?: 0)) {
                    val entry = linesArray?.optJSONObject(i) ?: continue
                    add(
                        LyricLine(
                            timeMs = if (entry.isNull("t")) null else entry.optLong("t"),
                            text = entry.optString("text"),
                        ),
                    )
                }
            }
            LyricsSnapshot(
                state = json.optString("state", LyricsSnapshot.STATE_NOT_FOUND),
                trackId = track?.stringOrNull("id"),
                trackName = track?.stringOrNull("name"),
                artist = track?.stringOrNull("artist"),
                lines = lines,
                linesIncluded = json.optBoolean("lines_included", true),
                positionMs = json.optLong("position_ms", 0L),
                isPlaying = json.optBoolean("is_playing", false),
            )
        }
    }

    fun checkNow(): ApiResult<Unit> = post("/api/playback/check-now") { }

    /** Returns the new skipping_paused value reported by the server. */
    fun togglePause(): ApiResult<Boolean> = post("/api/playback/toggle-pause") { body ->
        JSONObject(body).optBoolean("skipping_paused", false)
    }

    fun skipOnePause(): ApiResult<TrackRef> = post("/api/playback/skip-one-pause", ::trackRef)

    fun toggleLike(): ApiResult<LikeResult> = post("/api/playback/toggle-like") { body ->
        LikeResult(JSONObject(body).optBoolean("is_liked", false), trackRef(body))
    }

    /**
     * expectedTrackId is what the caller saw playing when the user confirmed. The
     * server answers 409 rather than deleting anything if the song moved on.
     */
    fun removeFromPlaylist(expectedTrackId: String?): ApiResult<TrackRef> {
        val payload = JSONObject().put("expected_track_id", expectedTrackId).toString()
        return execute(
            Request.Builder()
                .url(url("/api/playback/remove-from-playlist"))
                .post(payload.toRequestBody(JSON_MEDIA_TYPE)),
            ::trackRef,
        )
    }

    // Steering-wheel fallback. Media buttons normally reach Spotify directly; these
    // only matter if routing ever lands on this app instead.
    fun next(): ApiResult<Unit> = post("/api/playback/next") { }

    fun previous(): ApiResult<Unit> = post("/api/playback/previous") { }

    fun pause(): ApiResult<Unit> = post("/api/playback/pause") { }

    fun resume(): ApiResult<Unit> = post("/api/playback/resume") { }

    private fun trackRef(body: String): TrackRef {
        val json = JSONObject(body)
        return TrackRef(json.stringOrNull("track_name"), json.stringOrNull("artist"))
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
                    ApiResult.Err(errorMessage(response.code, body), response.code)
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
        val error = json?.stringOrNull("error")
        val detail = json?.stringOrNull("detail")
        return error ?: detail ?: "Server error ($code)"
    }

    private fun url(path: String): String = baseUrl + path

    companion object {
        const val UNREACHABLE = "Server unreachable"
        private const val TIMEOUT_SECONDS = 5L
        private val EMPTY_BODY = "".toRequestBody(null)
        private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()

        /** One client for the process — settings changes only swap baseUrl/token. */
        private val http = OkHttpClient.Builder()
            .connectTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .readTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .writeTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .callTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .build()
    }
}

/**
 * optString on a JSON null yields the four-character string "null" on Android, which
 * would compare equal to nothing and render as a track name. Check isNull first.
 */
private fun JSONObject.stringOrNull(key: String): String? =
    if (isNull(key)) null else optString(key).ifBlank { null }

private fun JSONObject.booleanOrNull(key: String): Boolean? =
    if (isNull(key)) null else optBoolean(key)
