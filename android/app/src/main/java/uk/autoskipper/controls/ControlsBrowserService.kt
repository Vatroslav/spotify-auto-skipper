package uk.autoskipper.controls

import android.os.Bundle
import android.support.v4.media.MediaBrowserCompat
import android.support.v4.media.MediaDescriptionCompat
import android.support.v4.media.session.MediaSessionCompat
import android.support.v4.media.session.PlaybackStateCompat
import androidx.media.MediaBrowserServiceCompat
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Browse tree of manual Auto-Skipper commands for Android Auto.
 *
 * Three rules hold the whole approach together (see docs/android-auto-controller.md):
 *  - the session never reports STATE_PLAYING or STATE_BUFFERING, so the system never
 *    routes steering-wheel media buttons here and Spotify keeps the media card;
 *  - the app never requests audio focus, so playback is never interrupted;
 *  - onLoadChildren has no side effects — Android Auto re-invokes it whenever it feels
 *    like it, and a command fired from there would repeat itself. Commands run only
 *    through onPlayFromMediaId.
 */
class ControlsBrowserService : MediaBrowserServiceCompat() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val commandRunning = AtomicBoolean(false)

    private lateinit var session: MediaSessionCompat
    private lateinit var settings: SettingsStore

    /** Last known server state; the browse labels render from this, never from a live call. */
    @Volatile
    private var skippingPaused = false

    private var messageResetJob: Job? = null

    override fun onCreate() {
        super.onCreate()
        settings = SettingsStore(this)

        session = MediaSessionCompat(this, TAG).apply {
            setCallback(SessionCallback())
            setPlaybackState(idleState())
            // Active so Android Auto delivers playFromMediaId and renders our error
            // messages. Activating does not claim media buttons — only actual playback
            // does, and this session never plays.
            isActive = true
        }
        sessionToken = session.sessionToken
    }

    override fun onDestroy() {
        scope.cancel()
        session.isActive = false
        session.release()
        super.onDestroy()
    }

    /**
     * Browse actions have server-side effects, so only Android Auto and our own
     * setup screen may connect — not every app on the phone.
     */
    override fun onGetRoot(
        clientPackageName: String,
        clientUid: Int,
        rootHints: Bundle?,
    ): BrowserRoot? {
        val allowed = clientPackageName == ANDROID_AUTO_PACKAGE || clientPackageName == packageName
        return if (allowed) BrowserRoot(ROOT_ID, null) else null
    }

    override fun onLoadChildren(
        parentId: String,
        result: Result<MutableList<MediaBrowserCompat.MediaItem>>,
    ) {
        if (parentId != ROOT_ID) {
            result.sendResult(mutableListOf())
            return
        }
        // Read-only refresh so the Pause/Resume label is current. GET only — never a command.
        result.detach()
        scope.launch {
            refreshState()
            result.sendResult(buildItems())
        }
    }

    private fun buildItems(): MutableList<MediaBrowserCompat.MediaItem> = mutableListOf(
        browseItem(CMD_CHECK_NOW, getString(R.string.cmd_check_now)),
        browseItem(
            CMD_TOGGLE_PAUSE,
            getString(
                if (skippingPaused) R.string.cmd_resume_skipping else R.string.cmd_pause_skipping,
            ),
        ),
    )

    private fun browseItem(mediaId: String, title: String): MediaBrowserCompat.MediaItem {
        val description = MediaDescriptionCompat.Builder()
            .setMediaId(mediaId)
            .setTitle(title)
            .build()
        return MediaBrowserCompat.MediaItem(
            description,
            MediaBrowserCompat.MediaItem.FLAG_PLAYABLE,
        )
    }

    private inner class SessionCallback : MediaSessionCompat.Callback() {
        override fun onPlayFromMediaId(mediaId: String?, extras: Bundle?) {
            runCommand(mediaId ?: return)
        }
    }

    private fun runCommand(mediaId: String) {
        // Single-flight: a second tap while a command is in the air is dropped.
        if (!commandRunning.compareAndSet(false, true)) return
        scope.launch {
            try {
                val client = settings.apiClient()
                if (client == null) {
                    showMessage(getString(R.string.msg_not_configured))
                    return@launch
                }
                val message = when (mediaId) {
                    CMD_CHECK_NOW -> when (val result = io { client.checkNow() }) {
                        is ApiResult.Ok -> getString(R.string.msg_check_sent)
                        is ApiResult.Err -> result.message
                    }

                    CMD_TOGGLE_PAUSE -> when (val result = io { client.togglePause() }) {
                        is ApiResult.Ok -> getString(
                            if (result.value) {
                                R.string.msg_skipping_paused
                            } else {
                                R.string.msg_skipping_resumed
                            },
                        )

                        is ApiResult.Err -> result.message
                    }

                    else -> "Unknown command"
                }
                refreshState()
                notifyChildrenChanged(ROOT_ID)
                showMessage(message)
            } finally {
                commandRunning.set(false)
            }
        }
    }

    /** Pulls skipping_paused so the labels match the server. Keeps the last value on failure. */
    private suspend fun refreshState() {
        val client = settings.apiClient() ?: return
        when (val result = io { client.getPlayback() }) {
            is ApiResult.Ok -> skippingPaused = result.value.skippingPaused
            is ApiResult.Err -> Unit
        }
    }

    /**
     * The only channel for user feedback on a car screen: a short STATE_ERROR with
     * setErrorMessage, then back to STATE_NONE. Never STATE_PLAYING.
     */
    private fun showMessage(message: String) {
        messageResetJob?.cancel()
        session.setPlaybackState(
            playbackStateBuilder()
                .setState(
                    PlaybackStateCompat.STATE_ERROR,
                    PlaybackStateCompat.PLAYBACK_POSITION_UNKNOWN,
                    0f,
                )
                .setErrorMessage(PlaybackStateCompat.ERROR_CODE_APP_ERROR, message)
                .build(),
        )
        messageResetJob = scope.launch {
            delay(MESSAGE_DURATION_MS)
            session.setPlaybackState(idleState())
        }
    }

    private fun idleState(): PlaybackStateCompat = playbackStateBuilder()
        .setState(
            PlaybackStateCompat.STATE_NONE,
            PlaybackStateCompat.PLAYBACK_POSITION_UNKNOWN,
            0f,
        )
        .build()

    private fun playbackStateBuilder(): PlaybackStateCompat.Builder =
        PlaybackStateCompat.Builder().setActions(PlaybackStateCompat.ACTION_PLAY_FROM_MEDIA_ID)

    private suspend fun <T> io(block: () -> T): T = withContext(Dispatchers.IO) { block() }

    companion object {
        private const val TAG = "AutoSkipperControls"
        private const val ROOT_ID = "root"
        private const val CMD_CHECK_NOW = "cmd:check_now"
        private const val CMD_TOGGLE_PAUSE = "cmd:toggle_pause"
        private const val ANDROID_AUTO_PACKAGE = "com.google.android.projection.gearhead"
        private const val MESSAGE_DURATION_MS = 4000L
    }
}
