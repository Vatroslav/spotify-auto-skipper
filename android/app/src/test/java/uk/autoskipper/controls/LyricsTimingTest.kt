package uk.autoskipper.controls

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * The clock arithmetic behind the car display. Every case here is one the
 * driver would otherwise have to catch while driving.
 */
class LyricsTimingTest {

    private val anchorElapsed = 1_000_000L

    private val lines = listOf(
        LyricLine(10_000, "first"),
        LyricLine(20_000, "second"),
        LyricLine(30_000, "third"),
        LyricLine(40_000, "fourth"),
        LyricLine(50_000, "fifth"),
        LyricLine(60_000, "sixth"),
    )

    private fun timing(positionMs: Long, playing: Boolean = true) = LyricsTiming(
        lines = lines,
        anchorPositionMs = positionMs,
        anchorElapsedMs = anchorElapsed,
        isPlaying = playing,
    )

    private fun after(seconds: Long) = anchorElapsed + seconds * 1000

    @Test
    fun `position advances with the local clock while playing`() {
        assertEquals(35_000, timing(25_000).positionAt(after(10)))
    }

    @Test
    fun `position stands still while paused`() {
        assertEquals(25_000, timing(25_000, playing = false).positionAt(after(10)))
    }

    @Test
    fun `position never runs backwards if the clock reading is stale`() {
        assertEquals(25_000, timing(25_000).positionAt(anchorElapsed - 5_000))
    }

    @Test
    fun `the opening line shows during the intro`() {
        // Nothing has been sung yet at 3s — the first line is still the right thing to show.
        assertEquals(0, timing(3_000).currentIndex(anchorElapsed))
    }

    @Test
    fun `the line that just started is the current one`() {
        assertEquals(2, timing(30_000).currentIndex(anchorElapsed))
        assertEquals(2, timing(39_999).currentIndex(anchorElapsed))
        assertEquals(3, timing(40_000).currentIndex(anchorElapsed))
    }

    @Test
    fun `the last line stays current to the end of the song`() {
        assertEquals(5, timing(200_000).currentIndex(anchorElapsed))
    }

    @Test
    fun `next line is due at the gap to the next timestamp`() {
        // Long literals: millisUntilNextLine is nullable, so JUnit boxes both
        // sides and an Int literal would never equal a Long.
        assertEquals(5_000L, timing(25_000).millisUntilNextLine(anchorElapsed))
    }

    @Test
    fun `next line accounts for time already elapsed since the anchor`() {
        // Anchored at 25s, three seconds ago: 2s left of the gap to 30s.
        assertEquals(2_000L, timing(25_000).millisUntilNextLine(after(3)))
    }

    @Test
    fun `nothing is due after the last line`() {
        assertNull(timing(59_000).millisUntilNextLine(after(5)))
    }

    @Test
    fun `nothing is due while paused`() {
        assertNull(timing(25_000, playing = false).millisUntilNextLine(anchorElapsed))
    }

    @Test
    fun `unsynced lyrics never schedule a tick`() {
        val untimed = LyricsTiming(
            lines = listOf(LyricLine(null, "a"), LyricLine(null, "b")),
            anchorPositionMs = 0,
            anchorElapsedMs = anchorElapsed,
            isPlaying = true,
        )
        assertNull(untimed.millisUntilNextLine(anchorElapsed))
        assertEquals(0, untimed.currentIndex(anchorElapsed))
    }

    @Test
    fun `window starts at the current line`() {
        val visible = timing(30_000).window(anchorElapsed, size = 3)
        assertEquals(listOf("third", "fourth", "fifth"), visible.map { it.text })
    }

    @Test
    fun `window stays full near the end instead of shrinking`() {
        // Current line is the last one; a naive slice would show a single row.
        val visible = timing(60_000).window(anchorElapsed, size = 3)
        assertEquals(listOf("fourth", "fifth", "sixth"), visible.map { it.text })
    }

    @Test
    fun `window larger than the lyrics returns everything once`() {
        val visible = timing(10_000).window(anchorElapsed, size = 50)
        assertEquals(6, visible.size)
    }

    @Test
    fun `manual paging overrides the song position`() {
        val visible = timing(60_000).window(anchorElapsed, size = 2, manualStart = 0)
        assertEquals(listOf("first", "second"), visible.map { it.text })
    }

    @Test
    fun `manual paging past the end is pulled back into range`() {
        val visible = timing(10_000).window(anchorElapsed, size = 2, manualStart = 99)
        assertEquals(listOf("fifth", "sixth"), visible.map { it.text })
    }

    @Test
    fun `empty lyrics produce no window and no ticks`() {
        val empty = LyricsTiming(emptyList(), 0, anchorElapsed, isPlaying = true)
        assertEquals(0, empty.window(anchorElapsed, size = 5).size)
        assertNull(empty.millisUntilNextLine(anchorElapsed))
        assertEquals(0, empty.currentIndex(anchorElapsed))
    }
}
