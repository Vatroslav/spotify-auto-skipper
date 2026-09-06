package uk.autoskipper.controls

import android.content.ContentResolver
import android.net.Uri
import android.os.Bundle
import android.support.v4.media.MediaBrowserCompat
import android.support.v4.media.MediaDescriptionCompat
import android.support.v4.media.session.MediaSessionCompat
import android.support.v4.media.session.PlaybackStateCompat
import androidx.annotation.DrawableRes
import androidx.media.MediaBrowserServiceCompat
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
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
 *
 * Feedback is shaped by what the first car test showed: Android Auto decides right
 * after a tap whether the selection loaded, so the playback state has to change
 * synchronously or it shows its own "Could not load your selection". The lasting
 * confirmation is the relabelled list, not the message.
 */
class ControlsBrowserService : MediaBrowserServiceCompat() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val commandRunning = AtomicBoolean(false)

    private lateinit var session: MediaSessionCompat
    private lateinit var settings: SettingsStore
    private lateinit var lyrics: LyricsSection

    /** Last known server state; browse labels render from this, never from a live call. */
    private var state = PlaybackSnapshot.UNKNOWN
    private var hasState = false

    /** Result of the last command, shown as that row's subtitle until the next one. */
    private var feedback: Feedback? = null

    private var subscribers = 0
    private var pollJob: Job? = null
    private var messageResetJob: Job? = null

    private data class Feedback(val mediaId: String, val text: String)

    override fun onCreate() {
        super.onCreate()
        settings = SettingsStore(this)
        lyrics = LyricsSection(this, scope, settings) {
            notifyChildrenChanged(LyricsSection.LYRICS_ROOT)
        }

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
        if (parentId == LyricsSection.LYRICS_ROOT) {
            // Rendered from whatever the section already holds — the car screen
            // never waits on the network here, the section refreshes itself.
            result.sendResult(lyrics.items())
            return
        }
        if (parentId != ROOT_ID) {
            result.sendResult(mutableListOf())
            return
        }
        if (!hasState) {
            // Cold start: there is nothing worth rendering yet, so wait for one snapshot.
            result.detach()
            scope.launch {
                refreshState()
                result.sendResult(buildItems())
            }
            return
        }
        // Warm: render from the last snapshot so the car screen never waits on the
        // network, then relabel if the server has moved on. GET only — never a command.
        result.sendResult(buildItems())
        scope.launch { refreshAndNotify() }
    }

    /** Polling runs only while something is actually browsing us — an Auto disconnect ends it. */
    override fun onSubscribe(id: String, options: Bundle?) {
        if (id == LyricsSection.LYRICS_ROOT) {
            lyrics.onOpened()
            return
        }
        if (id != ROOT_ID) return
        subscribers++
        startPolling()
    }

    override fun onUnsubscribe(id: String) {
        if (id == LyricsSection.LYRICS_ROOT) {
            lyrics.onClosed()
            return
        }
        if (id != ROOT_ID) return
        subscribers = (subscribers - 1).coerceAtLeast(0)
        if (subscribers == 0) {
            pollJob?.cancel()
            pollJob = null
        }
    }

    private fun startPolling() {
        if (pollJob?.isActive == true) return
        pollJob = scope.launch {
            while (isActive) {
                delay(POLL_INTERVAL_MS)
                refreshAndNotify()
            }
        }
    }

    // ── Browse tree ──────────────────────────────────────────────

    private fun buildItems(): MutableList<MediaBrowserCompat.MediaItem> {
        val s = state
        val items = mutableListOf<MediaBrowserCompat.MediaItem>()

        items += item(
            mediaId = CMD_STATUS,
            title = nowPlayingLabel(s),
            subtitle = getString(
                if (s.skippingPaused) R.string.status_skipping_paused else R.string.status_skipping_active,
            ),
            icon = R.drawable.ic_status,
        )

        items += item(
            mediaId = CMD_CHECK_NOW,
            title = getString(R.string.cmd_check_now),
            subtitle = feedbackFor(CMD_CHECK_NOW),
            icon = R.drawable.ic_check_now,
        )

        items += item(
            mediaId = CMD_TOGGLE_PAUSE,
            title = getString(
                if (s.skippingPaused) R.string.cmd_resume_skipping else R.string.cmd_pause_skipping,
            ),
            subtitle = feedbackFor(CMD_TOGGLE_PAUSE),
            icon = if (s.skippingPaused) R.drawable.ic_resume_skipping else R.drawable.ic_pause_skipping,
        )

        val exempt = s.trackId != null && s.trackId == s.skipExemptTrackId
        items += item(
            mediaId = CMD_SKIP_ONE_PAUSE,
            title = if (exempt) {
                getString(R.string.cmd_wont_skip, s.trackName.orEmpty())
            } else {
                getString(R.string.cmd_dont_skip)
            },
            subtitle = feedbackFor(CMD_SKIP_ONE_PAUSE),
            icon = R.drawable.ic_dont_skip,
        )

        val liked = s.isLiked == true
        items += item(
            mediaId = CMD_TOGGLE_LIKE,
            title = getString(if (liked) R.string.cmd_like_remove else R.string.cmd_like_add),
            subtitle = feedbackFor(CMD_TOGGLE_LIKE),
            icon = if (liked) R.drawable.ic_like_remove else R.drawable.ic_like_add,
        )

        // No trash playlist means a removed track has no backup copy, so the command
        // is not offered at all rather than offered and refused.
        if (s.trashConfigured) {
            items += item(
                mediaId = CMD_REMOVE,
                title = getString(R.string.cmd_remove),
                subtitle = feedbackFor(CMD_REMOVE),
                icon = R.drawable.ic_remove,
            )
        }

        // Last on purpose: the command rows above are muscle memory by now, and
        // this one is opened deliberately rather than hit in passing.
        items += lyrics.rootItem()

        return items
    }

    private fun nowPlayingLabel(s: PlaybackSnapshot): String = when {
        s.trackName == null -> getString(R.string.status_nothing_playing)
        s.artist == null -> getString(R.string.status_now_playing_track_only, s.trackName)
        else -> getString(R.string.status_now_playing, s.trackName, s.artist)
    }

    private fun feedbackFor(mediaId: String): String? =
        feedback?.takeIf { it.mediaId == mediaId }?.text

    private fun item(
        mediaId: String,
        title: String,
        subtitle: String?,
        @DrawableRes icon: Int,
    ): MediaBrowserCompat.MediaItem {
        val description = MediaDescriptionCompat.Builder()
            .setMediaId(mediaId)
            .setTitle(title)
            .setSubtitle(subtitle)
            .setIconUri(resourceUri(icon))
            .build()
        return MediaBrowserCompat.MediaItem(
            description,
            MediaBrowserCompat.MediaItem.FLAG_PLAYABLE,
        )
    }

    private fun resourceUri(@DrawableRes resId: Int): Uri = Uri.Builder()
        .scheme(ContentResolver.SCHEME_ANDROID_RESOURCE)
        .authority(packageName)
        .appendPath(resId.toString())
        .build()

    // ── Commands ─────────────────────────────────────────────────

    private inner class SessionCallback : MediaSessionCompat.Callback() {
        override fun onPlayFromMediaId(mediaId: String?, extras: Bundle?) {
            onItemTapped(mediaId ?: return)
        }

        // Steering-wheel fallback. Media buttons should reach Spotify directly; these
        // only fire if routing ever lands here, and then they forward rather than drop.
        override fun onSkipToNext() = runTransport { it.next() }

        override fun onSkipToPrevious() = runTransport { it.previous() }

        override fun onPause() = runTransport { it.pause() }

        override fun onPlay() = runTransport { it.resume() }
    }

    private fun onItemTapped(mediaId: String) {
        // Lyrics rows are display, not commands: they page the text locally and
        // must not go through the command path (no "Working…", no server call).
        if (mediaId == LyricsSection.LYRICS_MESSAGE) return
        if (lyrics.onItemTapped(mediaId)) return

        // Remove acts on the track the row is naming. With no snapshot there is nothing
        // to name, and firing blind would delete whatever Spotify has moved on to.
        if (mediaId == CMD_REMOVE && state.trackId == null) {
            showMessage(getString(R.string.msg_nothing_playing))
            return
        }
        if (!commandRunning.compareAndSet(false, true)) {
            showMessage(getString(R.string.msg_busy))
            return
        }
        // Synchronous state change: Android Auto judges the tap immediately and shows
        // its own generic failure if nothing happens before the HTTP round trip.
        showMessage(getString(R.string.msg_working))
        feedback = null
        runCommand(mediaId)
    }

    private fun runCommand(mediaId: String) {
        scope.launch {
            try {
                val client = settings.apiClient()
                if (client == null) {
                    showMessage(getString(R.string.msg_not_configured))
                    return@launch
                }
                val outcome = execute(client, mediaId) ?: return@launch
                // The status row has no subtitle of its own, so its confirmation lands
                // on the Check Now row it shares an action with.
                val row = if (mediaId == CMD_STATUS) CMD_CHECK_NOW else mediaId
                feedback = Feedback(row, outcome.subtitle)
                refreshState()
                notifyChildrenChanged(ROOT_ID)
                showMessage(outcome.message)
            } finally {
                commandRunning.set(false)
            }
        }
    }

    /** Runs one browse command. Null means the media id was not one of ours. */
    private suspend fun execute(client: ApiClient, mediaId: String): Outcome? = when (mediaId) {
        CMD_STATUS, CMD_CHECK_NOW -> io { client.checkNow() }.outcome {
            getString(R.string.feedback_sent) to getString(R.string.msg_check_sent)
        }

        CMD_TOGGLE_PAUSE -> io { client.togglePause() }.outcome { paused ->
            getString(R.string.feedback_done) to getString(
                if (paused) R.string.msg_skipping_paused else R.string.msg_skipping_resumed,
            )
        }

        CMD_SKIP_ONE_PAUSE -> io { client.skipOnePause() }.outcome { track ->
            getString(R.string.feedback_done) to
                getString(R.string.msg_wont_skip, track.name.orEmpty())
        }

        CMD_TOGGLE_LIKE -> io { client.toggleLike() }.outcome { result ->
            getString(R.string.feedback_done) to getString(
                if (result.isLiked) R.string.msg_liked else R.string.msg_unliked,
            )
        }

        CMD_REMOVE -> io { client.removeFromPlaylist(state.trackId) }.outcome { track ->
            getString(R.string.feedback_removed) to
                getString(R.string.msg_removed, track.name.orEmpty())
        }

        else -> null
    }

    /** Feedback for a finished command: the row subtitle that stays, the message that fades. */
    private data class Outcome(val subtitle: String, val message: String)

    private fun <T> ApiResult<T>.outcome(onOk: (T) -> Pair<String, String>): Outcome = when (this) {
        is ApiResult.Ok -> {
            val (subtitle, message) = onOk(value)
            Outcome(subtitle, message)
        }
        // The server already phrases its errors for humans; 409 is the one case the
        // car has extra context for — the song moved on between the last poll and the tap.
        is ApiResult.Err -> Outcome(
            getString(R.string.feedback_failed),
            if (code == HTTP_CONFLICT) getString(R.string.msg_track_changed) else message,
        )
    }

    private fun runTransport(run: (ApiClient) -> ApiResult<Unit>) {
        if (!commandRunning.compareAndSet(false, true)) return
        scope.launch {
            try {
                val client = settings.apiClient() ?: return@launch
                // Silent on success: a wheel press should not throw a message onto the screen.
                when (val result = io { run(client) }) {
                    is ApiResult.Ok -> refreshAndNotify()
                    is ApiResult.Err -> showMessage(result.message)
                }
            } finally {
                commandRunning.set(false)
            }
        }
    }

    // ── Server state ─────────────────────────────────────────────

    /** Pulls a fresh snapshot. Keeps the last one on failure rather than blanking the screen. */
    private suspend fun refreshState() {
        val client = settings.apiClient() ?: return
        when (val result = io { client.getPlayback() }) {
            is ApiResult.Ok -> applySnapshot(result.value)
            is ApiResult.Err -> Unit
        }
    }

    private fun applySnapshot(snapshot: PlaybackSnapshot) {
        state = snapshot
        hasState = true
    }

    private suspend fun refreshAndNotify() {
        val before = renderKey()
        refreshState()
        if (renderKey() != before) notifyChildrenChanged(ROOT_ID)
    }

    /**
     * Everything the browse list renders, as one string. Polls only notify Android Auto
     * when this changes, so a quiet server costs no list rebuilds.
     */
    private fun renderKey(): String = listOf(
        state.trackId,
        state.trackName,
        state.artist,
        state.skippingPaused,
        state.isLiked,
        state.skipExemptTrackId,
        state.trashConfigured,
        feedback?.mediaId,
        feedback?.text,
    ).joinToString("|")

    // ── Screen messages ──────────────────────────────────────────

    /**
     * The only direct channel to the car screen: a short STATE_ERROR with setErrorMessage,
     * then back to STATE_NONE. Never STATE_PLAYING.
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

    /**
     * The transport actions are declared so a stray media button has somewhere to land
     * (see SessionCallback). Declaring them does not claim the buttons — playback does.
     */
    private fun playbackStateBuilder(): PlaybackStateCompat.Builder =
        PlaybackStateCompat.Builder().setActions(
            PlaybackStateCompat.ACTION_PLAY_FROM_MEDIA_ID or
                PlaybackStateCompat.ACTION_SKIP_TO_NEXT or
                PlaybackStateCompat.ACTION_SKIP_TO_PREVIOUS or
                PlaybackStateCompat.ACTION_PAUSE or
                PlaybackStateCompat.ACTION_PLAY,
        )

    private suspend fun <T> io(block: () -> T): T = withContext(Dispatchers.IO) { block() }

    companion object {
        private const val TAG = "AutoSkipperControls"
        private const val ROOT_ID = "root"

        // The status row runs Check Now like the row below it, but carries its own id:
        // two items sharing one media id is a needless risk in someone else's list adapter.
        private const val CMD_STATUS = "cmd:status"
        private const val CMD_CHECK_NOW = "cmd:check_now"
        private const val CMD_TOGGLE_PAUSE = "cmd:toggle_pause"
        private const val CMD_SKIP_ONE_PAUSE = "cmd:skip_one_pause"
        private const val CMD_TOGGLE_LIKE = "cmd:toggle_like"
        private const val CMD_REMOVE = "cmd:remove"

        private const val ANDROID_AUTO_PACKAGE = "com.google.android.projection.gearhead"
        private const val MESSAGE_DURATION_MS = 4000L
        private const val POLL_INTERVAL_MS = 30_000L
        private const val HTTP_CONFLICT = 409
    }
}
