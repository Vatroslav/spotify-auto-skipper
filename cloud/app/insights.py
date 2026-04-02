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
        events.append(
            TrackEvent(
                time=time_str,
                artist=row["artist_name"],
                song=row["track_name"],
                outcome=row["outcome"],
                days_ago=row.get("days_ago"),
            )
        )
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

    # most_common(1) returns [((artist, song), count)] — unpack to a stable dict
    def _top_track(entries):
        if not entries:
            return None
        (artist, song), count = entries[0]
        return {"artist": artist, "song": song, "count": count}

    return {
        "songs_played": total,
        "songs_skipped": skip_count,
        "songs_kept": len(kept),
        "skip_rate": skip_rate,
        "unique_songs": unique_songs,
        "unique_artists": unique_artists,
        "most_skipped": _top_track(most_skipped),
        "most_played": _top_track(most_played),
        "longest_skip_streak": longest_skip_streak,
        "avg_skip_days": avg_skip_days,
    }


def generate_insights(metrics: dict, skip_window_days: int = 60) -> list[dict]:
    """Generate rule-based observations from computed metrics."""
    insights = []
    total = metrics["songs_played"]
    rate = metrics["skip_rate"]

    if total == 0:
        insights.append(
            {
                "icon": "info",
                "title": "No activity",
                "detail": "No songs were detected on this date.",
            }
        )
        return insights

    if rate > 50:
        insights.append(
            {
                "icon": "warning",
                "title": "High skip rate",
                "detail": (
                    f"{rate:.0f}% of songs were skipped. Your skip window "
                    f"({skip_window_days} days) might be too large \u2014 "
                    f"try lowering it so fewer songs get flagged."
                ),
            }
        )
    elif rate < 10 and total > 5:
        insights.append(
            {
                "icon": "info",
                "title": "Low skip rate",
                "detail": (
                    f"Only {rate:.0f}% of songs were skipped. Your playlist size and skip window seem well balanced."
                ),
            }
        )

    streak = metrics["longest_skip_streak"]
    if streak >= 4:
        insights.append(
            {
                "icon": "warning",
                "title": "Long skip streak",
                "detail": (
                    f"{streak} songs were skipped in a row. If this happens "
                    f"often, enable restart-pattern detection or lower the threshold."
                ),
            }
        )

    ms = metrics["most_skipped"]
    if ms and ms["count"] >= 3:
        insights.append(
            {
                "icon": "warning",
                "title": "Frequently skipped song",
                "detail": f'"{ms["song"]}" by {ms["artist"]} was skipped {ms["count"]} times.',
            }
        )

    avg = metrics["avg_skip_days"]
    if avg is not None and avg < 7:
        insights.append(
            {
                "icon": "warning",
                "title": "Skipping very recent songs",
                "detail": (
                    f"Skipped songs were listened to an average of {avg:.0f} days ago. "
                    f"You may want to reduce the skip window for a fresher mix."
                ),
            }
        )

    if not insights:
        insights.append(
            {
                "icon": "info",
                "title": "Looking good",
                "detail": "No issues detected. Everything seems well balanced.",
            }
        )

    return insights


def compute_metrics_all(events_by_date: list[tuple[str, list["TrackEvent"]]]) -> dict | None:
    """Compute aggregated metrics across all dates, plus daily records.

    Parameters
    ----------
    events_by_date : list of (date_str, [TrackEvent]) tuples, sorted by date.

    Returns dict with same base keys as compute_metrics(), plus record fields.
    Returns None if no events exist.
    """
    if not events_by_date:
        return None

    all_events: list[TrackEvent] = []

    # Per-day tracking for records
    best_busiest = ("", 0)
    best_most_skips = ("", 0)
    best_skip_rate = ("", 0.0)
    best_streak = ("", 0)
    best_oldest = None  # {"artist", "song", "days_ago", "date"}

    for date_str, day_events in events_by_date:
        all_events.extend(day_events)
        day_total = len(day_events)
        day_skipped = [e for e in day_events if e.outcome == "skipped"]
        day_skip_count = len(day_skipped)

        if day_total > best_busiest[1]:
            best_busiest = (date_str, day_total)

        if day_skip_count > best_most_skips[1]:
            best_most_skips = (date_str, day_skip_count)

        if day_total >= 5:
            day_rate = day_skip_count / day_total * 100
            if day_rate > best_skip_rate[1]:
                best_skip_rate = (date_str, day_rate)

        streak = 0
        day_best_streak = 0
        for e in day_events:
            if e.outcome == "skipped":
                streak += 1
                day_best_streak = max(day_best_streak, streak)
            else:
                streak = 0
        if day_best_streak > best_streak[1]:
            best_streak = (date_str, day_best_streak)

        for e in day_events:
            if e.days_ago is not None:
                if best_oldest is None or e.days_ago > best_oldest["days_ago"]:
                    best_oldest = {
                        "artist": e.artist,
                        "song": e.song,
                        "days_ago": e.days_ago,
                        "date": date_str,
                    }

    if not all_events:
        return None

    metrics = compute_metrics(all_events)
    metrics.update(
        {
            "total_days": len(events_by_date),
            "oldest_scrobble": best_oldest,
            "busiest_day": {"date": best_busiest[0], "count": best_busiest[1]},
            "most_skips_day": {"date": best_most_skips[0], "count": best_most_skips[1]},
            "highest_skip_rate_day": {"date": best_skip_rate[0], "rate": best_skip_rate[1]},
            "longest_streak_day": {"date": best_streak[0], "streak": best_streak[1]},
        }
    )
    return metrics


def generate_insights_all(metrics: dict, skip_window_days: int = 60) -> list[dict]:
    """Generate all-time observations from aggregated metrics."""
    insights = []
    total = metrics["songs_played"]
    days = metrics["total_days"]
    rate = metrics["skip_rate"]

    insights.append(
        {
            "icon": "info",
            "title": "Total activity",
            "detail": (
                f"{total:,} songs processed across {days} day{'s' if days != 1 else ''} ({total / days:.0f}/day avg)."
            ),
        }
    )

    if rate > 50:
        insights.append(
            {
                "icon": "warning",
                "title": "High overall skip rate",
                "detail": (
                    f"{rate:.0f}% of all songs were skipped. Consider lowering "
                    f"the skip window ({skip_window_days} days) for a better balance."
                ),
            }
        )
    elif rate < 10 and total > 20:
        insights.append(
            {
                "icon": "info",
                "title": "Low overall skip rate",
                "detail": (
                    f"Only {rate:.0f}% of songs were skipped across all time. Your settings seem well balanced."
                ),
            }
        )

    streak = metrics["longest_skip_streak"]
    if streak >= 6:
        sd = metrics["longest_streak_day"]
        insights.append(
            {
                "icon": "warning",
                "title": "All-time skip streak",
                "detail": (
                    f"{sd['streak']} songs skipped in a row ({sd['date']}). "
                    f"Consider enabling restart-pattern detection."
                ),
            }
        )

    ms = metrics["most_skipped"]
    if ms and ms["count"] >= 5:
        insights.append(
            {
                "icon": "warning",
                "title": "Most skipped song",
                "detail": f'"{ms["song"]}" by {ms["artist"]} was skipped {ms["count"]} times total.',
            }
        )

    avg = metrics["avg_skip_days"]
    if avg is not None and avg < 7:
        insights.append(
            {
                "icon": "warning",
                "title": "Skipping very recent songs",
                "detail": (
                    f"Skipped songs were listened to an average of {avg:.1f} days ago overall. "
                    f"A smaller skip window might help."
                ),
            }
        )

    if len(insights) == 1:
        insights.append(
            {
                "icon": "info",
                "title": "Looking good",
                "detail": "No issues detected across your listening history.",
            }
        )

    return insights
