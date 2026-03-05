"""
Log parser, metrics computation, and rule-based insights engine.
Reads daily log files and produces structured listening statistics.
"""

import os
import re
from collections import Counter
from dataclasses import dataclass, field


# ── Regex patterns matching exact log output from app.py ──────────

_RE_TIMESTAMP = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\s*(.*)$")

_RE_PLAYING = re.compile(
    r"\U0001f3b5 Currently playing:\s+(.+?)\s+\u2013\s+(.+)"
)
_RE_SKIPPED = re.compile(
    r"\u23ed\ufe0f Already listened to (\d+) days? ago\s*\u2014\s*skipping"
)
_RE_NEVER_SKIP = re.compile(
    r"\U0001f3a4 Artist is in never-skip list\s*\u2014\s*not skipping"
)
_RE_LIKED = re.compile(
    r"\U0001f49a Track is in Liked Songs\s*\u2014\s*not skipping"
)
_RE_OLDER_WINDOW = re.compile(
    r"\u2705 The last scrobble is older than the window\s*\u2014\s*not skipping"
)
_RE_NO_SCROBBLE = re.compile(
    r"\u2139\ufe0f There's no scrobble for this song\s*\u2014\s*not skipping"
)
_RE_RECOMMENDATION = re.compile(
    r"\u2728 Smart Shuffle recommendation:\s+(.+?)\s+\u2013\s+(.+)"
)
_RE_RESTART = re.compile(
    r"\u26a0\ufe0f Detected repeating pattern .+\u2014\s*restarting playlist"
)


# ── Data structures ───────────────────────────────────────────────

@dataclass
class TrackEvent:
    time: str
    artist: str
    song: str
    outcome: str          # skipped | played | liked | never_skip | no_scrobble
    days_ago: int | None = None


@dataclass
class DaySummary:
    date: str
    track_events: list[TrackEvent] = field(default_factory=list)
    recommendations: list[tuple[str, str]] = field(default_factory=list)
    restart_count: int = 0


# ── Log parser ────────────────────────────────────────────────────

def get_available_dates(log_dir: str) -> list[str]:
    """Return sorted list of YYYY-MM-DD strings for available log files."""
    if not os.path.isdir(log_dir):
        return []
    dates = []
    for f in os.listdir(log_dir):
        if re.match(r"\d{4}-\d{2}-\d{2}\.txt$", f):
            dates.append(f[:-4])
    dates.sort()
    return dates


def parse_log_file(log_dir: str, date_str: str) -> DaySummary | None:
    """Parse a single day's log file. Returns None if file not found."""
    path = os.path.join(log_dir, f"{date_str}.txt")
    if not os.path.isfile(path):
        return None

    summary = DaySummary(date=date_str)
    current_artist = None
    current_song = None
    current_time = ""

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            m = _RE_TIMESTAMP.match(line)
            if not m:
                continue
            ts, text = m.group(1), m.group(2)

            # Currently playing — sets state for next decision line
            m2 = _RE_PLAYING.match(text)
            if m2:
                current_artist = m2.group(1)
                current_song = m2.group(2)
                current_time = ts
                continue

            # Skip decision lines — all require a preceding "currently playing"
            if current_artist is None:
                # Check non-track events even without current track
                if _RE_RECOMMENDATION.match(text):
                    mr = _RE_RECOMMENDATION.match(text)
                    summary.recommendations.append((mr.group(1), mr.group(2)))
                elif _RE_RESTART.match(text):
                    summary.restart_count += 1
                continue

            m2 = _RE_SKIPPED.match(text)
            if m2:
                days = int(m2.group(1))
                summary.track_events.append(TrackEvent(
                    time=current_time, artist=current_artist,
                    song=current_song, outcome="skipped", days_ago=days,
                ))
                current_artist = None
                continue

            m2 = _RE_NEVER_SKIP.match(text)
            if m2:
                summary.track_events.append(TrackEvent(
                    time=current_time, artist=current_artist,
                    song=current_song, outcome="never_skip",
                ))
                current_artist = None
                continue

            m2 = _RE_LIKED.match(text)
            if m2:
                summary.track_events.append(TrackEvent(
                    time=current_time, artist=current_artist,
                    song=current_song, outcome="liked",
                ))
                current_artist = None
                continue

            m2 = _RE_OLDER_WINDOW.match(text)
            if m2:
                summary.track_events.append(TrackEvent(
                    time=current_time, artist=current_artist,
                    song=current_song, outcome="played",
                ))
                current_artist = None
                continue

            m2 = _RE_NO_SCROBBLE.match(text)
            if m2:
                summary.track_events.append(TrackEvent(
                    time=current_time, artist=current_artist,
                    song=current_song, outcome="no_scrobble",
                ))
                current_artist = None
                continue

            # Smart Shuffle recommendation
            m2 = _RE_RECOMMENDATION.match(text)
            if m2:
                summary.recommendations.append((m2.group(1), m2.group(2)))
                continue

            # Playlist restart
            if _RE_RESTART.match(text):
                summary.restart_count += 1

    return summary


# ── Metrics computation ───────────────────────────────────────────

def compute_metrics(summary: DaySummary) -> dict:
    """Compute flat metrics dict from a parsed day summary."""
    events = summary.track_events
    total = len(events)
    skipped = [e for e in events if e.outcome == "skipped"]
    kept = [e for e in events if e.outcome != "skipped"]

    skip_count = len(skipped)
    skip_rate = (skip_count / total * 100) if total > 0 else 0.0

    unique_songs = len({(e.artist, e.song) for e in events})
    unique_artists = len({e.artist for e in events})

    # Most skipped / most played song
    skip_counter = Counter((e.artist, e.song) for e in skipped)
    play_counter = Counter((e.artist, e.song) for e in kept)
    most_skipped = skip_counter.most_common(1)
    most_played = play_counter.most_common(1)

    # Longest skip streak
    longest_skip_streak = 0
    current_streak = 0
    for e in events:
        if e.outcome == "skipped":
            current_streak += 1
            longest_skip_streak = max(longest_skip_streak, current_streak)
        else:
            current_streak = 0

    # Average days_ago for skipped tracks
    skip_days = [e.days_ago for e in skipped if e.days_ago is not None]
    avg_skip_days = (sum(skip_days) / len(skip_days)) if skip_days else None

    return {
        "songs_played": total,
        "songs_skipped": skip_count,
        "songs_kept": len(kept),
        "skip_rate": skip_rate,
        "unique_songs": unique_songs,
        "unique_artists": unique_artists,
        "most_skipped": (most_skipped[0][0], most_skipped[0][1]) if most_skipped else None,
        "most_played": (most_played[0][0], most_played[0][1]) if most_played else None,
        "longest_skip_streak": longest_skip_streak,
        "avg_skip_days": avg_skip_days,
        "recommendations_count": len(summary.recommendations),
        "restart_count": summary.restart_count,
    }


# ── Rule-based insights ──────────────────────────────────────────

def generate_insights(metrics: dict, skip_window_days: int = 30) -> list[dict]:
    """Generate rule-based observations from computed metrics.

    Returns list of dicts with keys: icon ('warning'|'info'), title, detail.
    """
    insights = []

    total = metrics["songs_played"]
    rate = metrics["skip_rate"]

    if total == 0:
        insights.append({
            "icon": "info",
            "title": "No activity",
            "detail": "No songs were detected on this date.",
        })
        return insights

    if rate > 50:
        insights.append({
            "icon": "warning",
            "title": "High skip rate",
            "detail": (
                f"{rate:.0f}% of songs were skipped. Your skip window "
                f"({skip_window_days} days) might be too large \u2014 "
                f"try lowering it so fewer songs get flagged."
            ),
        })
    elif rate < 10 and total > 5:
        insights.append({
            "icon": "info",
            "title": "Low skip rate",
            "detail": (
                f"Only {rate:.0f}% of songs were skipped. Your playlist "
                f"size and skip window seem well balanced."
            ),
        })

    streak = metrics["longest_skip_streak"]
    if streak >= 4:
        insights.append({
            "icon": "warning",
            "title": "Long skip streak",
            "detail": (
                f"{streak} songs were skipped in a row. If this happens "
                f"often, enable restart-pattern detection or lower the threshold."
            ),
        })

    restarts = metrics["restart_count"]
    if restarts > 0:
        times = "time" if restarts == 1 else "times"
        insights.append({
            "icon": "info",
            "title": "Playlist restarts",
            "detail": f"The playlist was restarted {restarts} {times} due to repeating skip patterns.",
        })

    ms = metrics["most_skipped"]
    if ms and ms[1] >= 3:
        artist, song = ms[0]
        insights.append({
            "icon": "warning",
            "title": "Frequently skipped song",
            "detail": f"\"{song}\" by {artist} was skipped {ms[1]} times.",
        })

    recs = metrics["recommendations_count"]
    if recs > 0:
        insights.append({
            "icon": "info",
            "title": "Smart Shuffle active",
            "detail": f"{recs} Smart Shuffle recommendation{'s' if recs != 1 else ''} detected.",
        })

    avg = metrics["avg_skip_days"]
    if avg is not None and avg < 7:
        insights.append({
            "icon": "warning",
            "title": "Skipping very recent songs",
            "detail": (
                f"Skipped songs were listened to an average of {avg:.0f} days ago. "
                f"You may want to reduce the skip window for a fresher mix."
            ),
        })

    if not insights:
        insights.append({
            "icon": "info",
            "title": "Looking good",
            "detail": "No issues detected. Everything seems well balanced.",
        })

    return insights
