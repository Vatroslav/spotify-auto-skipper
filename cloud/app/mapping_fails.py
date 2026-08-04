"""Last.fm mapping-issue candidates for the Insights page.

A track earns an event here when the worker failed to find a fresh scrobble for
it — outcome 'no_scrobble' (Last.fm has nothing under that name) or 'played'
(the newest scrobble predates the skip window). Two or more such events, with no
positive outcome in between, used to be the whole heuristic.

That over-reports badly, because 'played' is usually just a race with the clock.
The worker asks Last.fm about a track shortly after it starts, but Last.fm only
accepts a scrobble halfway through the track (or after four minutes, whichever
comes first) and then backdates it to the start. In that gap the scrobble
genuinely does not exist yet, so a track whose mapping works perfectly gets an
event logged against it anyway — and on the list it looks identical to a real
name mismatch.

So the events are re-checked here against the scrobbles Last.fm has *now*: an
event with a scrobble sitting next to its timestamp was that race, not a mapping
failure, and drops out. A track with fewer than MIN_EVENTS suspicious events
left is not a candidate at all.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.database import get_all_track_aliases, get_mapping_fail_events
from app.lastfm_api import LASTFM_ERROR, get_track_scrobble_times

logger = logging.getLogger(__name__)

# How far from an event's timestamp a scrobble may sit and still be that event's
# own play.
#
# A track_events timestamp is when the worker *checked* Last.fm; a scrobble's
# timestamp is when the track *started*. The scrobble is therefore the older of
# the two, by however deep into the track the worker caught it. On a normal
# track change that is a poll interval; but when playback was already running
# (container restart, un-pause, wake from idle polling) the worker checks a
# track that may be nearly over — and this library runs to 20-minute tracks.
# 30 minutes covers that worst case with room to spare.
MATCH_BEFORE = timedelta(minutes=30)
# A scrobble should never post-date the check that missed it; this only absorbs
# clock skew between the container and the uts Last.fm stamped.
MATCH_AFTER = timedelta(minutes=5)

MIN_EVENTS = 2

# Last.fm asks for no more than ~5 requests/second.
LASTFM_CONCURRENCY = 4
LASTFM_DELAY = 0.2

# The endpoint runs on every Insights page load and costs one Last.fm call per
# candidate, so scrobble history is cached per queried name. Only the Last.fm
# side is cached: dismissals and freshly added aliases come from the database on
# every call, so the Dismiss and Add alias buttons still take effect at once.
CACHE_TTL = timedelta(minutes=10)
CACHE_MAX_ENTRIES = 200

# (artist, name) -> (fetched_at, covered_since_uts, scrobble uts list)
_scrobble_cache: dict[tuple[str, str], tuple[datetime, int, list[int]]] = {}


def _parse_event_ts(ts: str) -> datetime | None:
    """Parse a track_events timestamp — SQLite CURRENT_TIMESTAMP, UTC, no zone."""
    if not ts:
        return None
    try:
        return datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        logger.warning("[MappingFails] Unparseable event timestamp %r", ts)
        return None


def _has_scrobble_near(event_ts: datetime, scrobble_uts: list[int]) -> bool:
    """True if any scrobble falls in this event's tolerance window."""
    lo = (event_ts - MATCH_BEFORE).timestamp()
    hi = (event_ts + MATCH_AFTER).timestamp()
    return any(lo <= uts <= hi for uts in scrobble_uts)


async def _scrobble_times(
    artist: str, name: str, since_uts: int, http: httpx.AsyncClient
) -> list[int] | str:
    """Cached ``get_track_scrobble_times``. Returns LASTFM_ERROR on failure."""
    # Last.fm's lookup is case-insensitive, so names differing only in case hit
    # the same scrobbles and share one cache entry.
    key = (artist.casefold(), name.casefold())
    now = datetime.now(timezone.utc)
    cached = _scrobble_cache.get(key)
    if cached is not None:
        fetched_at, covered_since, times = cached
        if now - fetched_at < CACHE_TTL and covered_since <= since_uts:
            return times

    times = await get_track_scrobble_times(artist, name, since_uts, http=http)
    await asyncio.sleep(LASTFM_DELAY)  # stay under Last.fm's rate limit
    if times is LASTFM_ERROR:
        return LASTFM_ERROR  # a transient failure must never be cached

    if len(_scrobble_cache) > CACHE_MAX_ENTRIES:
        _scrobble_cache.clear()  # crude bound; entries are cheap to refetch
    _scrobble_cache[key] = (now, since_uts, times)
    return times


async def _attach_scrobbles(candidates: list[dict]):
    """Fetch each candidate's scrobble history into its ``scrobbles`` key."""
    aliases = await get_all_track_aliases()
    sem = asyncio.Semaphore(LASTFM_CONCURRENCY)

    async def one(c: dict, http: httpx.AsyncClient):
        # Query the name the worker itself used, alias included, so the check
        # reproduces the lookup that produced these events.
        name = (
            aliases["by_id"].get(c["track_id"])
            or aliases["by_artist_name"].get((c["artist_name"], c["track_name"]))
            or c["track_name"]
        )
        earliest = min(ts for ts, _ in c["events"]) - MATCH_BEFORE
        async with sem:
            c["scrobbles"] = await _scrobble_times(
                c["artist_name"], name, int(earliest.timestamp()), http
            )

    async with httpx.AsyncClient(timeout=20) as http:
        await asyncio.gather(*(one(c, http) for c in candidates))


async def get_mapping_fail_candidates(skip_window_days: int) -> list[dict]:
    """Return tracks that look like genuine Last.fm mapping failures.

    Qualifying events are grouped per track_id (so different album versions of
    the same song stay independent), the ones a scrobble explains are dropped,
    and a track survives only if MIN_EVENTS or more suspicious events remain.

    A track whose Last.fm lookup fails keeps every one of its events: a network
    blip must not quietly hide a real mapping problem.
    """
    events = await get_mapping_fail_events(skip_window_days)

    by_track: dict[str, dict] = {}
    for e in events:
        ts = _parse_event_ts(e["timestamp"])
        if ts is None:
            continue
        c = by_track.setdefault(
            e["track_id"],
            {
                "track_id": e["track_id"],
                "track_name": e["track_name"],
                "artist_name": e["artist_name"],
                "album_name": None,
                "events": [],
            },
        )
        # Rows are oldest-first, so the most recent naming wins.
        c["track_name"] = e["track_name"]
        c["artist_name"] = e["artist_name"]
        if e["album_name"]:
            c["album_name"] = e["album_name"]
        c["events"].append((ts, e["outcome"]))

    # Filtering only ever removes events, so anything already under the
    # threshold can be dropped before spending a Last.fm call on it.
    candidates = [c for c in by_track.values() if len(c["events"]) >= MIN_EVENTS]
    if not candidates:
        return []

    await _attach_scrobbles(candidates)

    result = []
    for c in candidates:
        scrobbles = c["scrobbles"]
        if scrobbles is LASTFM_ERROR:
            kept = c["events"]
            logger.warning(
                "[MappingFails] Last.fm lookup failed for '%s - %s' — keeping all %d events",
                c["artist_name"], c["track_name"], len(kept),
            )
        else:
            kept = [(ts, outcome) for ts, outcome in c["events"] if not _has_scrobble_near(ts, scrobbles)]
        if len(kept) < MIN_EVENTS:
            continue
        result.append(
            {
                "track_id": c["track_id"],
                "track_name": c["track_name"],
                "artist_name": c["artist_name"],
                "album_name": c["album_name"],
                "total_count": len(kept),
                "no_scrobble_count": sum(1 for _, o in kept if o == "no_scrobble"),
                "played_count": sum(1 for _, o in kept if o == "played"),
                "last_seen": max(ts for ts, _ in kept).strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

    # Worst offenders first, then most recent. Two stable sorts, low to high key.
    result.sort(key=lambda c: c["last_seen"], reverse=True)
    result.sort(key=lambda c: c["total_count"], reverse=True)
    return result
