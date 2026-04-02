"""
Rediscovery background job — scans a playlist against Last.fm scrobble history
and creates a new playlist with tracks not listened to recently.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.lastfm_api import LASTFM_ERROR, get_last_play_date

logger = logging.getLogger(__name__)

LASTFM_DELAY = 0.25  # seconds between Last.fm calls (~4 req/s)
LASTFM_ERROR_DELAY = 5.0  # seconds to wait after a Last.fm error
LASTFM_MAX_RETRIES = 2  # retries per track on transient errors
REDISCOVERY_THRESHOLD_DAYS = 60


async def run_rediscovery_job(app_state, playlist_id: str, playlist_name: str):
    """
    Main rediscovery job. Runs as an asyncio task.

    Phase 1: Fetch all tracks from the source playlist.
    Phase 2: Check each track against Last.fm.
    Phase 3: Create output playlist with qualifying tracks.
    """
    client = app_state.spotify_client
    threshold = datetime.now(timezone.utc) - timedelta(days=REDISCOVERY_THRESHOLD_DAYS)

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

        for i, track in enumerate(all_tracks):
            # Check for cancellation
            if asyncio.current_task().cancelled():
                raise asyncio.CancelledError()

            artist = track["artist"]
            name = track["name"]
            uri = track["uri"]

            # Query Last.fm with retries
            result = None
            for attempt in range(LASTFM_MAX_RETRIES + 1):
                result = await get_last_play_date(artist, name)
                if result is not LASTFM_ERROR:
                    break
                if attempt < LASTFM_MAX_RETRIES:
                    await asyncio.sleep(LASTFM_ERROR_DELAY)

            if result is LASTFM_ERROR:
                skipped_errors += 1
            elif result is None:
                # Never scrobbled — qualifies
                qualifying.append({"artist": artist, "name": name, "uri": uri, "last_played": None})
            elif result < threshold:
                # Last scrobble older than threshold — qualifies
                qualifying.append(
                    {
                        "artist": artist,
                        "name": name,
                        "uri": uri,
                        "last_played": result.isoformat(),
                    }
                )

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

        if not qualifying:
            app_state.rediscovery_status = "completed"
            app_state.rediscovery_progress = {
                "phase": "done",
                "current": len(all_tracks),
                "total": len(all_tracks),
                "message": f"Done. No tracks older than {REDISCOVERY_THRESHOLD_DAYS} days found.",
            }
            return

        # ── Phase 3: Create playlist ─────────────────────────
        app_state.rediscovery_progress = {
            "phase": "create",
            "current": 0,
            "total": len(qualifying),
            "message": f"Creating playlist with {len(qualifying)} tracks...",
        }
        logger.info("[Rediscovery] Phase 3: creating playlist with %d tracks", len(qualifying))

        new_playlist = await client.create_playlist(
            name=playlist_name,
            description=f"Rediscovery: {len(qualifying)} tracks not listened to in {REDISCOVERY_THRESHOLD_DAYS}+ days",
        )
        if not new_playlist:
            app_state.rediscovery_status = "failed"
            app_state.rediscovery_progress["message"] = "Failed to create Spotify playlist."
            return

        uris = [t["uri"] for t in qualifying]
        success = await client.add_tracks_to_playlist(new_playlist["id"], uris)
        if not success:
            app_state.rediscovery_status = "failed"
            app_state.rediscovery_progress["message"] = "Failed to add tracks to playlist."
            return

        app_state.rediscovery_playlist_url = new_playlist["url"]
        app_state.rediscovery_status = "completed"
        app_state.rediscovery_progress = {
            "phase": "done",
            "current": len(qualifying),
            "total": len(all_tracks),
            "message": (
                f"Done! {len(qualifying)} tracks added to '{playlist_name}'. ({skipped_errors} skipped due to errors)"
                if skipped_errors
                else f"Done! {len(qualifying)} tracks added to '{playlist_name}'."
            ),
        }
        logger.info("[Rediscovery] Complete. Playlist URL: %s", new_playlist["url"])

    except asyncio.CancelledError:
        app_state.rediscovery_status = "idle"
        app_state.rediscovery_progress = {"phase": "cancelled", "message": "Cancelled."}
        logger.info("[Rediscovery] Job cancelled.")

    except Exception as e:
        app_state.rediscovery_status = "failed"
        app_state.rediscovery_progress = {"phase": "error", "message": f"Error: {e}"}
        logger.exception("[Rediscovery] Job failed: %s", e)
