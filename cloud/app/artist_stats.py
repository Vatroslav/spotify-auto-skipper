"""Daily per-artist scrobble breakdown for the dashboard chart.

Source: Last.fm scrobbles — the authoritative listening history — not the app's
own `track_events`, which only capture skip-detection while the worker runs and
would distort actual play counts (skipped tracks inflate, off-app plays vanish).

Counts are per-artist scrobbles (plays) per local day, for the last
WINDOW_DAYS full days, excluding today, limited to the global top artists.
Results are cached per (tz, end_date) since the data only changes once a day.
"""

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.lastfm_api import LASTFM_ERROR, get_recent_tracks

logger = logging.getLogger(__name__)

WINDOW_DAYS = 7
TOP_ARTISTS = 6

_cache: dict[str, dict] = {}


def _resolve_tz(tz: str) -> ZoneInfo:
    if tz:
        try:
            return ZoneInfo(tz)
        except Exception:
            logger.warning("[ArtistStats] Unknown tz %r — falling back to UTC", tz)
    return ZoneInfo("UTC")


async def get_artist_daily(tz: str = "") -> dict:
    """Per-day, per-artist scrobble counts for the last WINDOW_DAYS full days.

    Returns:
      {
        "start": "YYYY-MM-DD", "end": "YYYY-MM-DD",
        "artists": [name, ...],            # global top artists, count desc
        "days": [{"date", "counts": [int per top artist], "total"}],
        "error"?: str,                     # present only on Last.fm failure
      }
    """
    zone = _resolve_tz(tz)
    today = datetime.now(zone).date()
    end_date = today - timedelta(days=1)  # last full day, inclusive
    start_date = today - timedelta(days=WINDOW_DAYS)  # first full day, inclusive

    cache_key = f"{zone.key}|{end_date.isoformat()}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    # UTC window: [start 00:00 local, today 00:00 local)
    start_local = datetime.combine(start_date, datetime.min.time(), tzinfo=zone)
    end_local = datetime.combine(today, datetime.min.time(), tzinfo=zone)
    from_uts = int(start_local.astimezone(timezone.utc).timestamp())
    to_uts = int(end_local.astimezone(timezone.utc).timestamp()) - 1

    scrobbles = await get_recent_tracks(from_uts, to_uts)
    if scrobbles == LASTFM_ERROR:
        # Don't cache transient failures.
        return {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "artists": [],
            "days": [],
            "error": "Couldn't reach Last.fm.",
        }

    day_dates = [start_date + timedelta(days=i) for i in range(WINDOW_DAYS)]
    per_day: dict[str, dict[str, int]] = {d.isoformat(): {} for d in day_dates}
    total_by_artist: dict[str, int] = {}

    for s in scrobbles:
        local_date = datetime.fromtimestamp(s["uts"], tz=timezone.utc).astimezone(zone).date()
        if local_date < start_date or local_date > end_date:
            continue  # guard against boundary scrobbles outside the window
        artist = s["artist"]
        day_map = per_day[local_date.isoformat()]
        day_map[artist] = day_map.get(artist, 0) + 1
        total_by_artist[artist] = total_by_artist.get(artist, 0) + 1

    # Global top artists (count desc, then name for stable ordering/colors).
    top = sorted(total_by_artist.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_ARTISTS]
    top_artists = [name for name, _ in top]

    days = []
    for d in day_dates:
        day_map = per_day[d.isoformat()]
        counts = [day_map.get(a, 0) for a in top_artists]
        days.append(
            {
                "date": d.isoformat(),
                "counts": counts,
                "total": sum(counts),  # total across top artists only
            }
        )

    result = {
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "artists": top_artists,
        "days": days,
    }

    if len(_cache) > 8:
        _cache.clear()  # crude bound; keys roll daily, stale ones are harmless
    _cache[cache_key] = result
    return result
