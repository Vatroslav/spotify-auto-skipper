"""
Metrics computation and rule-based insights engine.
Adapted from desktop app — reads from DB instead of log files.
"""

from collections import Counter
from dataclasses import dataclass


@dataclass
class TrackEvent:
    time: str
    artist: str
    song: str
    outcome: str
    days_ago: int | None = None


def events_from_db_rows(rows: list[dict]) -> list[TrackEvent]:
    """Convert DB rows to TrackEvent objects."""
    events = []
    for row in rows:
        ts = row.get("timestamp", "")
        # Extract HH:MM:SS from timestamp string
        time_str = ts[11:19] if len(ts) >= 19 else ts
        events.append(TrackEvent(
            time=time_str,
            artist=row["artist_name"],
            song=row["track_name"],
            outcome=row["outcome"],
            days_ago=row.get("days_ago"),
        ))
    return events


def compute_metrics(events: list[TrackEvent]) -> dict:
    """Compute flat metrics dict from track events."""
    total = len(events)
    skipped = [e for e in events if e.outcome == "skipped"]
    kept = [e for e in events if e.outcome != "skipped"]

    skip_count = len(skipped)
    skip_rate = (skip_count / total * 100) if total > 0 else 0.0

    unique_songs = len({(e.artist, e.song) for e in events})
    unique_artists = len({e.artist for e in events})

    skip_counter = Counter((e.artist, e.song) for e in skipped)
    play_counter = Counter((e.artist, e.song) for e in kept)
    most_skipped = skip_counter.most_common(1)
    most_played = play_counter.most_common(1)

    longest_skip_streak = 0
    current_streak = 0
    for e in events:
        if e.outcome == "skipped":
            current_streak += 1
            longest_skip_streak = max(longest_skip_streak, current_streak)
        else:
            current_streak = 0

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
    }


def generate_insights(metrics: dict, skip_window_days: int = 60) -> list[dict]:
    """Generate rule-based observations from computed metrics."""
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

    ms = metrics["most_skipped"]
    if ms and ms[1] >= 3:
        artist, song = ms[0]
        insights.append({
            "icon": "warning",
            "title": "Frequently skipped song",
            "detail": f'"{song}" by {artist} was skipped {ms[1]} times.',
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
