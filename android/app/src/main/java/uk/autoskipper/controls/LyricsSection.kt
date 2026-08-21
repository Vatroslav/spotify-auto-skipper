package uk.autoskipper.controls

import android.content.Context
import android.support.v4.media.MediaBrowserCompat
import android.support.v4.media.MediaDescriptionCompat
import android.net.Uri
import android.os.SystemClock
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * The "Lyrics" branch of the browse tree.
 *
 * Two clocks drive this, and keeping them apart is the whole design:
 *
 *  - the server clock, polled rarely. It answers "what is playing, where is it,
 *    and what are the words". Polling it per line would be a request every few
 *    seconds for the length of every drive.
 *  - the phone clock, free. Between polls the position is extrapolated locally
 *    and the list is relabelled exactly when the next line starts — no polling
 *    loop can hit a lyric boundary accurately anyway.
 *
 * The visible window is several lines rather than one. Android Auto is known to
 * drop browse-list refreshes until the user re-enters the screen, and a window
 * degrades gracefully under that: a missed refresh leaves the reader looking at
 * lines that are merely a little behind, instead of at a stale single line with
 * no context.
 */
class LyricsSection(
    private val context: Context,
    private val scope: CoroutineScope,
    private val settings: SettingsStore,
    /** Relabels this branch on the car screen. */
    private val onChanged: () -> Unit,
) {

    private var snapshot: LyricsSnapshot? = null
    private var timing: LyricsTiming? = null

    /** Lyrics survive a position refresh: the server omits them once we hold them. */
    private var lines: List<LyricLine> = emptyList()
    private var linesTrackId: String? = null

    /** Non-null while the user is paging by hand; cleared when the song changes. */
    private var manualStart: Int? = null

    private var pollJob: Job? = null
    private var tickJob: Job? = null
    private var subscribed = false

    // ── Lifecycle ────────────────────────────────────────────────

    /** Called when the car opens this branch. Fetches immediately, then keeps it live. */
    fun onOpened() {
        if (subscribed) return
        subscribed = true
        pollJob = scope.launch {
            while (isActive) {
                refresh()
                delay(POLL_INTERVAL_MS)
            }
        }
    }

    /** Called when the car leaves this branch. Everything stops — no work off-screen. */
    fun onClosed() {
        subscribed = false
        pollJob?.cancel()
        pollJob = null
        tickJob?.cancel()
        tickJob = null
    }

    // ── Server state ─────────────────────────────────────────────

    private suspend fun refresh() {
        val client = settings.apiClient() ?: return
        val known = linesTrackId
        when (val result = io { client.getLyrics(known) }) {
            is ApiResult.Ok -> apply(result.value)
            is ApiResult.Err -> Unit // keep showing the last good lines rather than blanking
        }
    }

    private fun apply(fresh: LyricsSnapshot) {
        val trackChanged = fresh.trackId != linesTrackId
        if (trackChanged) {
            // A new song invalidates hand-paging and any lines we were holding.
            manualStart = null
            lines = emptyList()
            linesTrackId = null
        }
        if (fresh.linesIncluded) {
            lines = fresh.lines
            linesTrackId = fresh.trackId
        }

        snapshot = fresh
        timing = LyricsTiming(
            lines = lines,
            anchorPositionMs = fresh.positionMs,
            anchorElapsedMs = SystemClock.elapsedRealtime(),
            isPlaying = fresh.isPlaying,
        )
        onChanged()
        scheduleNextLine()
    }

    /**
     * Sleep until the current line stops being current, then relabel.
     *
     * Re-armed after every tick rather than run as a fixed-interval loop: lyric
     * lines are seconds apart at unpredictable spacing, and a fixed interval
     * would either lag behind them or rebuild the list for nothing.
     */
    private fun scheduleNextLine() {
        tickJob?.cancel()
        if (manualStart != null) return // hand-paging owns the view until the song changes

        val delayMs = timing?.millisUntilNextLine(SystemClock.elapsedRealtime()) ?: return
        tickJob = scope.launch {
            delay(delayMs + LINE_SETTLE_MS)
            onChanged()
            scheduleNextLine()
        }
    }

    // ── Browse items ─────────────────────────────────────────────

    fun rootItem(): MediaBrowserCompat.MediaItem = browsable(
        mediaId = LYRICS_ROOT,
        title = context.getString(R.string.lyrics_browse_title),
        subtitle = context.getString(R.string.lyrics_browse_subtitle),
    )

    /** The lines the car should show right now, or a single explanatory row. */
    fun items(): MutableList<MediaBrowserCompat.MediaItem> {
        val current = snapshot
            ?: return mutableListOf(message(context.getString(R.string.lyrics_loading)))

        val messageText = when (current.state) {
            LyricsSnapshot.STATE_NOTHING_PLAYING -> context.getString(R.string.lyrics_nothing_playing)
            LyricsSnapshot.STATE_INSTRUMENTAL -> context.getString(R.string.lyrics_instrumental)
            LyricsSnapshot.STATE_NOT_FOUND -> context.getString(R.string.lyrics_not_found)
            else -> null
        }
        if (messageText != null) return mutableListOf(message(messageText))
        if (lines.isEmpty()) return mutableListOf(message(context.getString(R.string.lyrics_loading)))

        val now = SystemClock.elapsedRealtime()
        val activeTiming = timing
        val start = manualStart ?: activeTiming?.currentIndex(now) ?: 0
        val visible = activeTiming?.window(now, WINDOW_SIZE, manualStart)
            ?: lines.take(WINDOW_SIZE)

        val items = mutableListOf<MediaBrowserCompat.MediaItem>()
        visible.forEachIndexed { offset, line ->
            val index = start + offset
            val isTop = offset == 0
            items += playable(
                mediaId = "$LYRICS_LINE_PREFIX$index",
                // An empty timed line is an instrumental gap in the LRC, not a blank row.
                title = line.text.ifBlank { INSTRUMENTAL_GAP },
                subtitle = if (isTop) topRowSubtitle(current) else null,
            )
        }
        return items
    }

    /**
     * The top row carries the mode, because it is the only row a driver reliably
     * reads. In hand-paging mode it doubles as the way back to automatic.
     */
    private fun topRowSubtitle(current: LyricsSnapshot): String = when {
        manualStart != null -> context.getString(R.string.lyrics_mode_manual)
        current.state == LyricsSnapshot.STATE_PLAIN_ONLY ->
            context.getString(R.string.lyrics_mode_untimed)
        !current.isPlaying -> context.getString(R.string.lyrics_mode_paused)
        else -> context.getString(R.string.lyrics_mode_auto)
    }

    /**
     * A tapped line becomes the top of the window.
     *
     * Tapping the line already on top means "follow the song again"; tapping
     * any line below means "hold here". That gives both the automatic and the
     * manual reading mode without spending a row on a Next button — a target a
     * driver would have to hunt for at the bottom of the list.
     *
     * Returns true when the tap was ours to handle.
     */
    fun onItemTapped(mediaId: String): Boolean {
        if (!mediaId.startsWith(LYRICS_LINE_PREFIX)) return false
        val index = mediaId.removePrefix(LYRICS_LINE_PREFIX).toIntOrNull() ?: return true

        val now = SystemClock.elapsedRealtime()
        val autoIndex = timing?.currentIndex(now) ?: 0
        manualStart = if (manualStart == null && index == autoIndex) {
            // Already following the song and the user tapped the current line —
            // read it as "hold here" rather than a no-op.
            index
        } else if (manualStart != null && index == manualStart) {
            null // back to following the song
        } else {
            index
        }

        onChanged()
        scheduleNextLine()
        return true
    }

    // ── Item builders ────────────────────────────────────────────

    private fun playable(mediaId: String, title: String, subtitle: String?) =
        MediaBrowserCompat.MediaItem(
            MediaDescriptionCompat.Builder()
                .setMediaId(mediaId)
                .setTitle(title)
                .setSubtitle(subtitle)
                .build(),
            MediaBrowserCompat.MediaItem.FLAG_PLAYABLE,
        )

    private fun browsable(mediaId: String, title: String, subtitle: String?) =
        MediaBrowserCompat.MediaItem(
            MediaDescriptionCompat.Builder()
                .setMediaId(mediaId)
                .setTitle(title)
                .setSubtitle(subtitle)
                .setIconUri(iconUri())
                .build(),
            MediaBrowserCompat.MediaItem.FLAG_BROWSABLE,
        )

    /** Non-tappable status row: a distinct media id the tap handler ignores. */
    private fun message(text: String) = MediaBrowserCompat.MediaItem(
        MediaDescriptionCompat.Builder()
            .setMediaId(LYRICS_MESSAGE)
            .setTitle(text)
            .build(),
        MediaBrowserCompat.MediaItem.FLAG_PLAYABLE,
    )

    private fun iconUri(): Uri = Uri.Builder()
        .scheme(android.content.ContentResolver.SCHEME_ANDROID_RESOURCE)
        .authority(context.packageName)
        .appendPath(R.drawable.ic_lyrics.toString())
        .build()

    private suspend fun <T> io(block: () -> T): T =
        kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { block() }

    companion object {
        const val LYRICS_ROOT = "lyrics:root"
        const val LYRICS_MESSAGE = "lyrics:message"
        private const val LYRICS_LINE_PREFIX = "lyrics:line:"

        /** Lines shown at once. Enough that a dropped refresh still leaves context. */
        private const val WINDOW_SIZE = 5

        /**
         * Catches the song change, a pause, and any seek. Line-to-line movement
         * does not come from here — it is timed locally.
         */
        private const val POLL_INTERVAL_MS = 20_000L

        /** Nudge past the boundary so rounding can't land the tick a hair early. */
        private const val LINE_SETTLE_MS = 40L

        private const val INSTRUMENTAL_GAP = "♪"
    }
}
