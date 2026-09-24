"""
Rediscovery background job — scans a playlist against Last.fm scrobble history
and creates playlists with tracks not listened to recently.

Several thresholds give exclusive buckets: each track lands only in the highest
threshold it has passed (thresholds 100, 500, 1000 → a track last heard 678
days ago goes to "500-999 days" only). Never-scrobbled tracks go into the
highest bucket, but are counted apart in the summary: some of them are mapping
failures (Spotify and Last.fm naming a track differently), not old songs.

The clean-up job works the other way: it empties a created playlist of
tracks heard since they went in, and of tracks Spotify no longer plays.
"""

import asyncio
import bisect
import logging
from datetime import datetime, timedelta, timezone

from app.database import add_rediscovery_link, get_track_events_since
from app.lastfm_api import LASTFM_ERROR, get_last_play_date, get_recent_tracks
from app.observability import report_exception

logger = logging.getLogger(__name__)

LASTFM_DELAY = 0.25  # seconds between Last.fm calls (~4 req/s)
LASTFM_ERROR_DELAY = 5.0  # seconds to wait after a Last.fm error
LASTFM_MAX_RETRIES = 2  # retries per track on transient errors
DEFAULT_THRESHOLD_DAYS = 60
MAX_THRESHOLDS = 5


def _build_buckets(thresholds_days: list[int]) -> list[dict]:
    """Return one bucket per threshold, ascending."""
    now = datetime.now(timezone.utc)
    buckets = []
    for i, days in enumerate(thresholds_days):
        upper = thresholds_days[i + 1] if i + 1 < len(thresholds_days) else None
        buckets.append(
            {
                "label": f"{days}-{upper - 1} days" if upper else f"{days}+ days",
                "cutoff": now - timedelta(days=days),
                "tracks": [],
            }
        )
    return buckets


async def run_rediscovery_job(app_state, playlist_id: str, playlist_name: str, thresholds_days: list[int]):
    """
    Main rediscovery job. Runs as an asyncio task.

    Phase 1: Fetch all tracks from the source playlist.
    Phase 2: Check each track against Last.fm and sort it into a bucket.
    Phase 3: Create one output playlist per non-empty bucket.
    """
    client = app_state.spotify_client
    buckets = _build_buckets(thresholds_days)
    highest = buckets[-1]

    try:
        # ── Phase 1: Fetch tracks ────────────────────────────
        app_state.rediscovery_status = "running"
        app_state.rediscovery_progress = {"phase": "fetch", "current": 0, "total": 0, "message": "Loading tracks..."}
        logger.info("[Rediscovery] Phase 1: fetching tracks from playlist %s", playlist_id)

        # Source name is only for logs and the link record; the job works without it.
        source_info = await client.get_playlist_info(playlist_id)
        source_name = (source_info or {}).get("name", "")

        all_tracks = []
        offset = 0
        total = 0
        while True:
            page = await client.get_playlist_tracks(playlist_id, limit=100, offset=offset)
            items = page.get("items", [])
            total = page.get("total", 0)
            all_tracks.extend(items)
            app_state.rediscovery_progress["current"] = len(all_tracks)
            app_state.rediscovery_progress["total"] = total
            app_state.rediscovery_progress["message"] = f"Loading tracks... {len(all_tracks)}/{total}"

            offset += 100
            if offset >= total:
                break

        logger.info("[Rediscovery] Fetched %d tracks", len(all_tracks))

        if not all_tracks:
            app_state.rediscovery_status = "failed"
            app_state.rediscovery_progress["message"] = "No tracks found in playlist."
            return

        # Tracks Spotify won't play in the user's country can never have been
        # scrobbled, so they'd all land in the highest bucket as "never
        # scrobbled". Drop them before spending Last.fm calls on them.
        to_check = [t for t in all_tracks if t["is_playable"] is not False]
        unavailable = len(all_tracks) - len(to_check)
        if any(t["is_playable"] is not None for t in all_tracks):
            unavailable_note = f" {unavailable} unavailable on Spotify skipped."
        else:
            # Relinking info missing entirely: say so rather than claim 0.
            unavailable_note = " Spotify sent no availability info, so unavailable tracks were not skipped."
            logger.warning("[Rediscovery] No is_playable in playlist tracks; unavailable tracks not filtered")

        # ── Phase 2: Check Last.fm ───────────────────────────
        app_state.rediscovery_progress = {
            "phase": "check",
            "current": 0,
            "total": len(to_check),
            "message": f"Checking Last.fm... 0/{len(to_check)}",
        }
        logger.info("[Rediscovery] Phase 2: checking %d tracks against Last.fm", len(to_check))

        qualifying = []
        skipped_errors = 0
        never_scrobbled = 0

        for i, track in enumerate(to_check):
            # Check for cancellation
            if asyncio.current_task().cancelled():
                raise asyncio.CancelledError()

            artist = track["artist"]
            name = track["name"]
            uri = track["uri"]
            track_id = track["id"]

            # Query Last.fm with retries
            result = None
            for attempt in range(LASTFM_MAX_RETRIES + 1):
                result = await get_last_play_date(artist, name, track_id)
                if result is not LASTFM_ERROR:
                    break
                if attempt < LASTFM_MAX_RETRIES:
                    await asyncio.sleep(LASTFM_ERROR_DELAY)

            if result is LASTFM_ERROR:
                skipped_errors += 1
            else:
                if result is None:
                    bucket = highest
                    never_scrobbled += 1
                else:
                    # Cutoffs fall as thresholds rise, so the last bucket whose
                    # cutoff the scrobble predates is the highest one it passed.
                    bucket = None
                    for b in buckets:
                        if result < b["cutoff"]:
                            bucket = b
                if bucket is not None:
                    entry = {
                        "artist": artist,
                        "name": name,
                        "uri": uri,
                        "last_played": result.isoformat() if result else None,
                        "bucket": bucket["label"],
                    }
                    bucket["tracks"].append(entry)
                    qualifying.append(entry)

            # Update progress every track
            app_state.rediscovery_progress["current"] = i + 1
            app_state.rediscovery_progress["message"] = (
                f"Checking Last.fm... {i + 1}/{len(to_check)} | Found: {len(qualifying)}"
            )

            # Throttle
            await asyncio.sleep(LASTFM_DELAY)

        logger.info(
            "[Rediscovery] Phase 2 done: %d qualifying, %d skipped (errors)",
            len(qualifying),
            skipped_errors,
        )

        app_state.rediscovery_results = qualifying

        # Built before Phase 3 so the counts survive a failed playlist write —
        # the scan is the costly part.
        summary = ", ".join(f"{b['label']}: {len(b['tracks'])}" for b in buckets)
        if never_scrobbled:
            summary += f" (of which {never_scrobbled} never scrobbled, in {highest['label']})"
        notes = unavailable_note + (f" {skipped_errors} skipped due to Last.fm errors." if skipped_errors else "")

        if not qualifying:
            app_state.rediscovery_status = "completed"
            app_state.rediscovery_progress = {
                "phase": "done",
                "current": len(to_check),
                "total": len(to_check),
                "message": f"Done. No tracks qualified ({summary}).{notes}",
            }
            return

        # ── Phase 3: Create playlists ────────────────────────
        to_create = [b for b in buckets if b["tracks"]]
        app_state.rediscovery_progress = {
            "phase": "create",
            "current": 0,
            "total": len(to_create),
            "message": f"Creating {len(to_create)} playlist(s)...",
        }
        logger.info("[Rediscovery] Phase 3: creating %d playlists (%s)", len(to_create), summary)

        created = []
        failed = []
        for n, b in enumerate(to_create, start=1):
            name = f"{playlist_name} ({b['label']})"
            count = len(b["tracks"])
            app_state.rediscovery_progress["current"] = n - 1
            app_state.rediscovery_progress["message"] = f"Creating '{name}' with {count} tracks..."
            description = (
                f"Rediscovery: {count} tracks last heard {b['label']} ago or never scrobbled"
                if b is highest and never_scrobbled
                else f"Rediscovery: {count} tracks last heard {b['label']} ago"
            )

            new_playlist = await client.create_playlist(name=name, description=description)
            if not new_playlist or not new_playlist["id"]:
                failed.append(f"{b['label']} (creating the playlist)")
                continue
            # Linked before the tracks go in: an incomplete playlist is still one
            # the user can play, and manual removes from it should reach the source.
            await add_rediscovery_link(new_playlist["id"], playlist_id, source_name)
            if not await client.add_tracks_to_playlist(new_playlist["id"], [t["uri"] for t in b["tracks"]]):
                failed.append(f"{b['label']} (adding tracks - the playlist exists but is incomplete)")
                continue
            created.append({"label": b["label"], "name": name, "count": count, "url": new_playlist["url"]})

        app_state.rediscovery_playlists = created
        if failed:
            message = f"Found {summary}. Spotify failed for: {'; '.join(failed)}.{notes}"
        else:
            message = f"Done! Created {len(created)} playlist(s): {summary}.{notes}"

        # Partial success still counts as completed so the created ones get links.
        app_state.rediscovery_status = "completed" if created else "failed"
        app_state.rediscovery_progress = {
            "phase": "done",
            "current": len(to_create),
            "total": len(to_create),
            "message": message,
        }
        logger.info("[Rediscovery] Complete. %d created, %d failed.", len(created), len(failed))

    except asyncio.CancelledError:
        app_state.rediscovery_status = "idle"
        app_state.rediscovery_progress = {"phase": "cancelled", "message": "Cancelled."}
        logger.info("[Rediscovery] Job cancelled.")

    except Exception as e:
        app_state.rediscovery_status = "failed"
        app_state.rediscovery_progress = {"phase": "error", "message": f"Error: {e}"}
        logger.exception("[Rediscovery] Job failed: %s", e)
        report_exception(e, component="rediscovery")


# ── Clean-up ─────────────────────────────────────────────────────

# Plays are paired with scrobbles by time and artist, not by track name.
# Rediscovery playlists gather exactly the tracks a name lookup gets wrong: one
# that Last.fm files under another name ("Darker Days - Remastered" for
# Spotify's "Darker Days") never looks heard, so the scan puts it in the
# highest bucket, and a name lookup would not see it played afterwards either.
#
# A scrobble is stamped with the moment its track started; the worker logs its
# track_events row once it has checked the track, a little later (on
# production 2 s to 4 min later, median about a minute). So a scrobble belongs
# to the earliest same-artist event logged within this window after its start.
PAIR_EARLY = 10  # seconds an event may precede its scrobble: clock skew only
PAIR_LATE = 1800  # the worker caught the track late: restart, un-pause, idle polling
# The worker logs a skip after skipping, when the next track has already
# started, so a skipped event must trail the scrobble it claims by more than that.
SKIPPED_MIN_LAG = 30


def _parse_added_at(value: str | None) -> datetime | None:
    """Spotify's added_at ("2026-09-19T14:03:12Z") as an aware datetime, else None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _loose(name: str) -> str:
    """Letters and digits only, casefolded: "Darker Days - Remastered" → "darkerdaysremastered"."""
    return "".join(ch for ch in name.casefold() if ch.isalnum())


def _same_song(a: str, b: str) -> bool:
    """Whether one name extends the other ("Darker Days" / "Darker Days - Remastered")."""
    a, b = _loose(a), _loose(b)
    return bool(a) and bool(b) and (a.startswith(b) or b.startswith(a))


def _heard_events(events: list[dict], scrobbles: list[dict]) -> list[dict]:
    """The worker events (oldest first) that have a Last.fm scrobble of their own.

    Each scrobble, oldest first, goes to the earliest unclaimed event of the
    same artist inside its window. When an album plays through several fit,
    and one whose name matches the scrobble's wins.
    """
    times = [e["uts"] for e in events]
    claimed = set()
    for s in sorted(scrobbles, key=lambda s: s["uts"]):
        artist = s["artist"].casefold()
        fits = []
        for i in range(bisect.bisect_left(times, s["uts"] - PAIR_EARLY), len(events)):
            e = events[i]
            lag = e["uts"] - s["uts"]
            if lag > PAIR_LATE:
                break
            if i in claimed or e["artist_name"].casefold() != artist:
                continue
            if e["outcome"] == "skipped" and lag < SKIPPED_MIN_LAG:
                continue
            fits.append(i)
        if fits:
            claimed.add(next((i for i in fits if _same_song(events[i]["track_name"], s["name"])), fits[0]))
    return [events[i] for i in sorted(claimed)]


async def _find_listened(tracks: list[dict]) -> tuple[set[str], int] | str:
    """URIs of the tracks heard since they went into the playlist.

    Returns (uris, tracks without an added_at), or LASTFM_ERROR when Last.fm
    can't be reached.
    """
    dated = []
    no_date = 0
    for t in tracks:
        added = _parse_added_at(t["added_at"])
        if added is None:
            no_date += 1
        else:
            dated.append((t, added.timestamp()))
    if not dated:
        return set(), no_date

    # Reach back PAIR_LATE past the oldest add: a play logged after it may have
    # started (and been scrobbled) that much earlier.
    since = int(min(added for _, added in dated)) - PAIR_LATE
    scrobbles = await get_recent_tracks(since, int(datetime.now(timezone.utc).timestamp()))
    if scrobbles is LASTFM_ERROR:
        return LASTFM_ERROR
    events = await get_track_events_since(since)

    # Keyed by id and by name too: the worker logs the id Spotify played, which
    # for a relinked track is not the one in the playlist.
    heard: dict = {}
    for e in _heard_events(events, scrobbles):
        for key in (e["track_id"], (e["artist_name"].casefold(), e["track_name"].casefold())):
            heard[key] = max(heard.get(key, 0), e["uts"])

    listened = set()
    for t, added in dated:
        last = max(heard.get(t["id"], 0), heard.get((t["artist"].casefold(), t["name"].casefold()), 0))
        if last > added:
            listened.add(t["uri"])
    return listened, no_date


async def run_cleanup_job(app_state, playlist_id: str, playlist_name: str):
    """
    Clean-up job: remove listened and unavailable tracks from one Rediscovery
    playlist. Runs in the same job slot as the scan, so only one of them runs
    at a time.

    A track counts as listened when the worker logged it playing after it went
    into the playlist (Spotify's added_at) and Last.fm has a scrobble for that
    play. The play may come from any context, not only this playlist. The
    source playlist is not touched: a track heard again still belongs there.

    Phase 1: Fetch all tracks of the playlist.
    Phase 2: Pair the worker's plays with Last.fm scrobbles.
    Phase 3: Remove the listened and unavailable tracks.
    """
    client = app_state.spotify_client

    try:
        # ── Phase 1: Fetch tracks ────────────────────────────
        app_state.rediscovery_status = "running"
        app_state.rediscovery_progress = {"phase": "fetch", "current": 0, "total": 0, "message": "Loading tracks..."}

        tracks = []
        offset = 0
        while True:
            page = await client.get_playlist_tracks(playlist_id, limit=100, offset=offset)
            tracks.extend(page.get("items", []))
            total = page.get("total", 0)
            app_state.rediscovery_progress["current"] = len(tracks)
            app_state.rediscovery_progress["total"] = total
            app_state.rediscovery_progress["message"] = f"Loading tracks... {len(tracks)}/{total}"

            offset += 100
            if offset >= total:
                break

        logger.info("[Rediscovery] Clean-up: %d tracks in '%s'", len(tracks), playlist_name)

        # ── Phase 2: Pair plays with scrobbles ───────────────
        app_state.rediscovery_progress = {
            "phase": "check",
            "current": 0,
            "total": 0,
            "message": "Matching plays to Last.fm scrobbles...",
        }

        # Sets: a track in the playlist twice is one removal (Spotify drops every copy).
        unavailable = {t["uri"] for t in tracks if t["is_playable"] is False}
        found = await _find_listened([t for t in tracks if t["is_playable"] is not False])
        if found is LASTFM_ERROR:
            app_state.rediscovery_status = "failed"
            app_state.rediscovery_progress = {
                "phase": "error",
                "message": "Last.fm could not be reached. Nothing was removed, try again.",
            }
            return
        listened, no_date = found

        notes = ""
        if tracks and all(t["is_playable"] is None for t in tracks):
            notes += " Spotify sent no availability info, so unavailable tracks were not removed."
        if no_date:
            notes += f" {no_date} kept because Spotify sent no date added."
        counts = f"{len(listened)} listened, {len(unavailable)} unavailable"

        # ── Phase 3: Remove ──────────────────────────────────
        uris = list(listened | unavailable)
        if uris:
            app_state.rediscovery_progress["message"] = f"Removing {len(uris)} tracks..."
            ok, error = await client.remove_tracks_from_playlist(playlist_id, uris)
            if not ok:
                logger.warning("[Rediscovery] Clean-up: removing from '%s' failed: %s", playlist_name, error)
                app_state.rediscovery_status = "failed"
                app_state.rediscovery_progress = {
                    "phase": "done",
                    "message": f"Found {counts}, but Spotify failed to remove them: {error}.{notes}",
                }
                return

        app_state.rediscovery_status = "completed"
        app_state.rediscovery_progress = {
            "phase": "done",
            "current": len(tracks),
            "total": len(tracks),
            "message": f"Done! Removed {len(uris)} tracks from '{playlist_name}' ({counts}).{notes}",
        }
        logger.info("[Rediscovery] Clean-up complete. %d removed from '%s'.", len(uris), playlist_name)

    except asyncio.CancelledError:
        app_state.rediscovery_status = "idle"
        app_state.rediscovery_progress = {"phase": "cancelled", "message": "Cancelled."}
        logger.info("[Rediscovery] Clean-up cancelled.")

    except Exception as e:
        app_state.rediscovery_status = "failed"
        app_state.rediscovery_progress = {"phase": "error", "message": f"Error: {e}"}
        logger.exception("[Rediscovery] Clean-up failed: %s", e)
        report_exception(e, component="rediscovery")
