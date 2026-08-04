"""Last.fm mapping-issue candidates for the Insights page.

A track earns an event here when the worker failed to find a fresh scrobble for
it — outcome 'no_scrobble' (Last.fm has nothing under that name) or 'played'
(the newest scrobble predates the skip window). Two or more such events, with no
positive outcome in between, used to be the whole heuristic.

That over-reports badly, because those events are usually just a race with the
clock. The worker asks Last.fm about a track shortly after it starts, but
Last.fm only accepts a scrobble halfway through the track (or after four
minutes, whichever comes first) and then backdates it to the start. In that gap
the scrobble genuinely does not exist yet, so a track whose mapping works
perfectly gets an event logged against it anyway — and on the list it looks
identical to a real name mismatch. On production this was 194 of 223 entries.

So the events are re-checked here against the scrobbles Last.fm has *now*, in
two passes:

  1. One index of the user's recent scrobbles covers every candidate at once —
     ~24 requests for a 60-day window against one request per candidate, and it
     does not get more expensive as the list grows. It matches on the literal
     scrobbled name, which is what Spotify submitted, so it settles the vast
     majority (192 of the 194 above).
  2. Whatever survives goes through ``user.getTrackScrobbles`` per track, which
     applies Last.fm's own name resolution and so catches the scrobbles stored
     under a canonicalised name (diacritics, mostly) that a literal match
     misses. Only the leftovers reach this pass, so it stays cheap.

An event with a scrobble sitting next to its timestamp was that race, not a
mapping failure, and drops out. A track with fewer than MIN_EVENTS suspicious
events left is not a candidate at all.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.database import get_all_track_aliases, get_mapping_fail_events
from app.lastfm_api import LASTFM_ERROR, get_recent_tracks, get_track_scrobble_times

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

# Pass 2 is cached per queried name. Only the Last.fm side is cached:
# dismissals and freshly added aliases are read from the database on every call,
# so the Dismiss and Add alias buttons still take effect at once.
TRACK_CACHE_TTL = timedelta(minutes=10)
TRACK_CACHE_MAX_ENTRIES = 500

# How much of the tail of the scrobble index a refresh re-fetches instead of
# trusting. Everything older than this is settled, but the recent end is not:
# Last.fm backdates a scrobble to the track's start, so one landing right now
# can carry a uts from a track-length ago — which a strict "everything since the
# last fetch" refresh would step straight over. An hour is well past the longest
# track in the library.
REFRESH_LOOKBACK = timedelta(minutes=60)

# Scrobbles covering [from_uts, until_uts] as (artist casefolded, name
# casefolded, uts). Process-local, rebuilt on restart.
_recent: dict = {"from_uts": 0, "until_uts": 0, "scrobbles": []}

# (artist, name) casefolded -> (fetched_at, covered_since_uts, uts list)
_track_cache: dict[tuple[str, str], tuple[datetime, int, list[int]]] = {}


def _parse_event_ts(ts: str) -> datetime | None:
    """Parse a track_events timestamp — SQLite CURRENT_TIMESTAMP, UTC, no zone."""
    if not ts:
        return None
    try:
        return datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        logger.warning("[MappingFails] Unparseable event timestamp %r", ts)
        return None


def _unexplained(events: list[tuple[datetime, str]], scrobble_uts: list[int]) -> list[tuple[datetime, str]]:
    """Drop the events that have a scrobble inside their tolerance window."""
    if not scrobble_uts:
        return events
    kept = []
    for ts, outcome in events:
        lo = (ts - MATCH_BEFORE).timestamp()
        hi = (ts + MATCH_AFTER).timestamp()
        if not any(lo <= uts <= hi for uts in scrobble_uts):
            kept.append((ts, outcome))
    return kept


async def _recent_index(since_uts: int) -> dict[tuple[str, str], list[int]] | None:
    """Scrobbles from ``since_uts`` on, indexed by casefolded (artist, track).

    Kept warm across calls, so only the first render after a restart pays for
    the whole window; later ones re-fetch just the tail (see REFRESH_LOOKBACK).

    Returns None when Last.fm is unreachable and nothing usable is cached — the
    caller must then not filter at all.
    """
    now_uts = int(datetime.now(timezone.utc).timestamp())
    # A previous fetch is reusable when it reached at least as far back as this
    # call needs. Keyed on the watermark, not on the list being non-empty — an
    # empty stretch is a real answer worth keeping.
    reusable = _recent["until_uts"] > 0 and _recent["from_uts"] <= since_uts
    fetch_from = (
        max(_recent["until_uts"] - int(REFRESH_LOOKBACK.total_seconds()), since_uts)
        if reusable
        else since_uts
    )

    fetched = await get_recent_tracks(fetch_from, now_uts)
    if fetched is LASTFM_ERROR:
        if not reusable:
            logger.warning("[MappingFails] Last.fm recent-tracks fetch failed with no cache — not filtering")
            return None
        # Keep serving the cached index and leave the watermark alone, so the
        # next render retries the same stretch.
        logger.warning("[MappingFails] Last.fm recent-tracks refresh failed — using the cached index")
        merged = _recent["scrobbles"]
    else:
        kept = [s for s in _recent["scrobbles"] if s[2] < fetch_from] if reusable else []
        merged = kept + [(s["artist"].casefold(), s["name"].casefold(), s["uts"]) for s in fetched]
        merged = [s for s in merged if s[2] >= since_uts]  # window slid forward
        _recent.update({"from_uts": since_uts, "until_uts": now_uts, "scrobbles": merged})

    index: dict[tuple[str, str], list[int]] = {}
    for artist, name, uts in merged:
        index.setdefault((artist, name), []).append(uts)
    return index


async def _track_scrobble_times(
    artist: str, name: str, since_uts: int, http: httpx.AsyncClient
) -> list[int] | str:
    """Cached ``get_track_scrobble_times``. Returns LASTFM_ERROR on failure."""
    # Last.fm's lookup is case-insensitive, so names differing only in case hit
    # the same scrobbles and share one cache entry.
    key = (artist.casefold(), name.casefold())
    now = datetime.now(timezone.utc)
    cached = _track_cache.get(key)
    if cached is not None:
        fetched_at, covered_since, times = cached
        if now - fetched_at < TRACK_CACHE_TTL and covered_since <= since_uts:
            return times

    times = await get_track_scrobble_times(artist, name, since_uts, http=http)
    await asyncio.sleep(LASTFM_DELAY)  # stay under Last.fm's rate limit
    if times is LASTFM_ERROR:
        return LASTFM_ERROR  # a transient failure must never be cached

    if len(_track_cache) > TRACK_CACHE_MAX_ENTRIES:
        _track_cache.clear()  # crude bound; entries are cheap to refetch
    _track_cache[key] = (now, since_uts, times)
    return times


async def _per_track_pass(candidates: list[dict]):
    """Re-check each candidate's leftover events against its own scrobble history."""
    sem = asyncio.Semaphore(LASTFM_CONCURRENCY)

    async def one(c: dict, http: httpx.AsyncClient):
        earliest = min(ts for ts, _ in c["events"]) - MATCH_BEFORE
        async with sem:
            times = await _track_scrobble_times(
                c["artist_name"], c["lastfm_name"], int(earliest.timestamp()), http
            )
        if times is LASTFM_ERROR:
            logger.warning(
                "[MappingFails] Last.fm lookup failed for '%s - %s' — keeping all %d events",
                c["artist_name"], c["lastfm_name"], len(c["events"]),
            )
            return
        c["events"] = _unexplained(c["events"], times)

    async with httpx.AsyncClient(timeout=20) as http:
        await asyncio.gather(*(one(c, http) for c in candidates))


def _as_list(groups: list[dict]) -> list[dict]:
    """Shape the surviving groups the way the Insights list expects them."""
    result = []
    for g in groups:
        events = g["events"]
        result.append(
            {
                "track_id": g["track_id"],
                "track_name": g["track_name"],
                "artist_name": g["artist_name"],
                "album_name": g["album_name"],
                "total_count": len(events),
                "no_scrobble_count": sum(1 for _, o in events if o == "no_scrobble"),
                "played_count": sum(1 for _, o in events if o == "played"),
                "last_seen": max(ts for ts, _ in events).strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    # Worst offenders first, then most recent. Two stable sorts, low key first.
    result.sort(key=lambda c: c["last_seen"], reverse=True)
    result.sort(key=lambda c: c["total_count"], reverse=True)
    return result


async def get_mapping_fail_candidates(skip_window_days: int) -> list[dict]:
    """Return tracks that look like genuine Last.fm mapping failures.

    Qualifying events are grouped per track_id (so different album versions of
    the same song stay independent), the ones a scrobble explains are dropped,
    and a track survives only if MIN_EVENTS or more suspicious events remain.

    Any Last.fm failure leaves the affected events in place: a network blip must
    not quietly hide a real mapping problem.
    """
    events = await get_mapping_fail_events(skip_window_days)

    groups: dict[str, dict] = {}
    for e in events:
        ts = _parse_event_ts(e["timestamp"])
        if ts is None:
            continue
        g = groups.setdefault(
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
        g["track_name"] = e["track_name"]
        g["artist_name"] = e["artist_name"]
        if e["album_name"]:
            g["album_name"] = e["album_name"]
        g["events"].append((ts, e["outcome"]))

    # Filtering only ever removes events, so anything already under the
    # threshold can be dropped before spending a Last.fm call on it.
    candidates = [g for g in groups.values() if len(g["events"]) >= MIN_EVENTS]
    if not candidates:
        return []

    # Query the name the worker itself used, alias included, so both passes
    # reproduce the lookup that produced these events.
    aliases = await get_all_track_aliases()
    for c in candidates:
        c["lastfm_name"] = (
            aliases["by_id"].get(c["track_id"])
            or aliases["by_artist_name"].get((c["artist_name"], c["track_name"]))
            or c["track_name"]
        )

    earliest = min(min(ts for ts, _ in c["events"]) for c in candidates) - MATCH_BEFORE
    index = await _recent_index(int(earliest.timestamp()))
    if index is None:
        # Last.fm is unreachable — report the unfiltered list rather than hang
        # the page on a per-track pass that would fail the same way.
        return _as_list(candidates)

    for c in candidates:
        c["events"] = _unexplained(
            c["events"], index.get((c["artist_name"].casefold(), c["lastfm_name"].casefold()), [])
        )
    survivors = [c for c in candidates if len(c["events"]) >= MIN_EVENTS]

    await _per_track_pass(survivors)

    return _as_list([c for c in survivors if len(c["events"]) >= MIN_EVENTS])
