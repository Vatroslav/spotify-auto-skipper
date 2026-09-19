"""
Rediscovery background job — scans a playlist against Last.fm scrobble history
and creates playlists with tracks not listened to recently.

Several thresholds give exclusive buckets: each track lands only in the highest
threshold it has passed (thresholds 100, 500, 1000 → a track last heard 678
days ago goes to "500-999 days" only). Never-scrobbled tracks go into the
highest bucket, but are counted apart in the summary: some of them are mapping
failures (Spotify and Last.fm naming a track differently), not old songs.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

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

        # ── Phase 2: Check Last.fm ───────────────────────────
        app_state.rediscovery_progress = {
            "phase": "check",
            "current": 0,
            "total": len(all_tracks),
            "message": f"Checking Last.fm... 0/{len(all_tracks)}",
        }
        logger.info("[Rediscovery] Phase 2: checking %d tracks against Last.fm", len(all_tracks))

        qualifying = []
        skipped_errors = 0
        never_scrobbled = 0

        for i, track in enumerate(all_tracks):
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
                f"Checking Last.fm... {i + 1}/{len(all_tracks)} | Found: {len(qualifying)}"
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
        errors_note = f" ({skipped_errors} skipped due to errors)" if skipped_errors else ""

        if not qualifying:
            app_state.rediscovery_status = "completed"
            app_state.rediscovery_progress = {
                "phase": "done",
                "current": len(all_tracks),
                "total": len(all_tracks),
                "message": f"Done. No tracks qualified ({summary}).{errors_note}",
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
            if not await client.add_tracks_to_playlist(new_playlist["id"], [t["uri"] for t in b["tracks"]]):
                failed.append(f"{b['label']} (adding tracks - the playlist exists but is incomplete)")
                continue
            created.append({"label": b["label"], "name": name, "count": count, "url": new_playlist["url"]})

        app_state.rediscovery_playlists = created
        if failed:
            message = f"Found {summary}. Spotify failed for: {'; '.join(failed)}.{errors_note}"
        else:
            message = f"Done! Created {len(created)} playlist(s): {summary}.{errors_note}"

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
