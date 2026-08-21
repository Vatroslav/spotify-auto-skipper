package uk.autoskipper.controls

/** One lyric line. `timeMs` is null for unsynced lyrics, which cannot scroll themselves. */
data class LyricLine(val timeMs: Long?, val text: String)

/**
 * Which lines to show right now, and when that answer next changes.
 *
 * The server is polled rarely — a track has one set of lyrics and playback
 * advances at a known rate, so the phone can work out the rest on its own.
 * Everything here is pure: the service supplies "now" and gets back a window
 * and a delay, which keeps the timing testable and the service free of clocks.
 */
class LyricsTiming(
    private val lines: List<LyricLine>,
    /** Playback position the server reported, and the local clock reading when it arrived. */
    private val anchorPositionMs: Long,
    private val anchorElapsedMs: Long,
    private val isPlaying: Boolean,
) {

    /** Playback position at local clock reading [nowElapsedMs]. */
    fun positionAt(nowElapsedMs: Long): Long {
        if (!isPlaying) return anchorPositionMs
        return anchorPositionMs + (nowElapsedMs - anchorElapsedMs).coerceAtLeast(0L)
    }

    /**
     * Index of the line being sung at [nowElapsedMs].
     *
     * Before the first timestamp the answer is 0 — the opening line is shown
     * during the intro rather than an empty screen. Untimed lyrics also return
     * 0, since without timings there is no "current" line to find.
     */
    fun currentIndex(nowElapsedMs: Long): Int {
        if (lines.isEmpty()) return 0
        val position = positionAt(nowElapsedMs)
        var index = 0
        for (i in lines.indices) {
            val t = lines[i].timeMs ?: return 0
            if (t > position) break
            index = i
        }
        return index
    }

    /**
     * Milliseconds until the current line stops being current, or null when
     * nothing further will change on its own (paused, unsynced, or past the
     * last line). Null tells the caller to stop scheduling wake-ups.
     */
    fun millisUntilNextLine(nowElapsedMs: Long): Long? {
        if (!isPlaying || lines.isEmpty()) return null
        val position = positionAt(nowElapsedMs)
        val next = lines.firstOrNull { (it.timeMs ?: return null) > position } ?: return null
        return ((next.timeMs ?: return null) - position).coerceAtLeast(0L)
    }

    /**
     * The visible slice: [size] lines starting at the current one.
     *
     * Starting at the current line rather than centring on it is deliberate.
     * Android Auto renders a browse list top-down with no way to highlight a
     * row, so the top row has to be the one being sung. The lines below it are
     * what is coming — that is the part a glance can use.
     *
     * Near the end of a song the window is pulled back so it stays full rather
     * than shrinking to a single row.
     */
    fun window(nowElapsedMs: Long, size: Int, manualStart: Int? = null): List<LyricLine> {
        if (lines.isEmpty() || size <= 0) return emptyList()
        val start = (manualStart ?: currentIndex(nowElapsedMs))
            .coerceIn(0, (lines.size - size).coerceAtLeast(0))
        return lines.subList(start, minOf(start + size, lines.size))
    }
}
