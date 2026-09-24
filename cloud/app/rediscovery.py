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
import logging
from datetime import datetime, timedelta, timezone

from app.database import add_rediscovery_link
from app.lastfm_api import LASTFM_ERROR, get_last_play_date
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


async def _last_play_date(track: dict) -> datetime | str | None:
    """Last scrobble of a playlist track, retrying transient Last.fm errors.

    Returns datetime, None (never scrobbled) or LASTFM_ERROR once retries run out.
    """
    result = None
    for attempt in range(LASTFM_MAX_RETRIES + 1):
        result = await get_last_play_date(track["artist"], track["name"], track["id"])
        if result is not LASTFM_ERROR:
            break
        if attempt < LASTFM_MAX_RETRIES:
            await asyncio.sleep(LASTFM_ERROR_DELAY)
    return result


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

            result = await _last_play_date(track)

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


def _parse_added_at(value: str | None) -> datetime | None:
    """Spotify's added_at ("2026-09-19T14:03:12Z") as an aware datetime, else None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


async def run_cleanup_job(app_state, playlist_id: str, playlist_name: str):
    """
    Clean-up job: remove listened and unavailable tracks from one Rediscovery
    playlist. Runs in the same job slot as the scan, so only one of them runs
    at a time.

    A track counts as listened when its last scrobble is newer than the moment
    it went into the playlist (Spotify's added_at). A play from any context
    counts, not only one started from the Rediscovery playlist. The source
    playlist is not touched: a track heard again still belongs there.

    Phase 1: Fetch all tracks of the playlist.
    Phase 2: Check each against Last.fm, then remove listened and unavailable ones.
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

        # ── Phase 2: Check Last.fm and clean ─────────────────
        app_state.rediscovery_progress = {
            "phase": "check",
            "current": 0,
            "total": len(tracks),
            "message": f"Checking Last.fm... 0/{len(tracks)}",
        }

        # Sets: a track in the playlist twice is one removal (Spotify drops every copy).
        listened = set()
        unavailable = set()
        lastfm_errors = 0
        no_date = 0

        for i, track in enumerate(tracks):
            if track["is_playable"] is False:
                unavailable.add(track["uri"])
            else:
                added = _parse_added_at(track["added_at"])
                if added is None:
                    no_date += 1
                else:
                    result = await _last_play_date(track)
                    if result is LASTFM_ERROR:
                        lastfm_errors += 1
                    elif result is not None and result > added:
                        listened.add(track["uri"])
                    await asyncio.sleep(LASTFM_DELAY)

            app_state.rediscovery_progress["current"] = i + 1
            app_state.rediscovery_progress["message"] = (
                f"Checking Last.fm... {i + 1}/{len(tracks)} | To remove: {len(listened) + len(unavailable)}"
            )

        notes = ""
        if tracks and all(t["is_playable"] is None for t in tracks):
            notes += " Spotify sent no availability info, so unavailable tracks were not removed."
        if lastfm_errors:
            notes += f" {lastfm_errors} kept because Last.fm failed."
        if no_date:
            notes += f" {no_date} kept because Spotify sent no date added."
        counts = f"{len(listened)} listened, {len(unavailable)} unavailable"

        uris = list(listened | unavailable)
        if uris:
            ok, error = await client.remove_tracks_from_playlist(playlist_id, uris)
            if not ok:
                logger.warning("[Rediscovery] Clean-up: removing from '%s' failed: %s", playlist_name, error)
                app_state.rediscovery_status = "failed"
                app_state.rediscovery_progress = {
                    "phase": "done",
                    "current": len(tracks),
                    "total": len(tracks),
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
