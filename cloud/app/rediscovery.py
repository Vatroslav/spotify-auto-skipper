"""
Rediscovery Playlist — background job that scans a playlist for tracks
not scrobbled in N days and creates a new playlist with those tracks.
"""

import asyncio
import logging
from datetime import datetime, timezone

from app.lastfm_api import get_last_play_date, LASTFM_ERROR
from app.state import app_state

logger = logging.getLogger(__name__)


def _default_job() -> dict:
    return {
        "status": "idle",
        "total_tracks": 0,
        "checked": 0,
        "found": 0,
        "current_track": "",
        "errors": 0,
        "started_at": None,
        "finished_at": None,
        "result_playlist_url": None,
        "error_message": None,
    }


async def run_rediscovery(source_playlist_id: str, threshold_days: int, hours_available: float):
    """Main job coroutine. Updates app_state.rediscovery_job throughout."""
    job = app_state.rediscovery_job
    client = app_state.spotify_client
    now = datetime.now(timezone.utc)

    try:
        job["status"] = "running"
        job["started_at"] = now.isoformat()
        logger.info("[Rediscovery] Starting — playlist %s, threshold %d days, %.1f hours",
                     source_playlist_id, threshold_days, hours_available)

        # 1. Fetch all tracks from source playlist
        tracks = await client.get_playlist_tracks(source_playlist_id)
        if not tracks:
            job["status"] = "error"
            job["error_message"] = "No tracks found in playlist (or failed to fetch)."
            job["finished_at"] = datetime.now(timezone.utc).isoformat()
            return

        job["total_tracks"] = len(tracks)
        logger.info("[Rediscovery] Fetched %d tracks", len(tracks))

        # 2. Calculate delay between Last.fm calls
        delay = max(1.0, (hours_available * 3600) / len(tracks))
        logger.info("[Rediscovery] Delay between checks: %.1f seconds", delay)

        # 3. Get user ID for playlist creation
        user_id = await client.get_current_user_id()
        if not user_id:
            job["status"] = "error"
            job["error_message"] = "Could not fetch Spotify user ID."
            job["finished_at"] = datetime.now(timezone.utc).isoformat()
            return

        # 4. Check each track against Last.fm
        qualifying = []
        for i, track in enumerate(tracks):
            # Check cancel flag
            if job["status"] == "cancelled":
                logger.info("[Rediscovery] Cancelled at track %d/%d", i + 1, len(tracks))
                job["finished_at"] = datetime.now(timezone.utc).isoformat()
                return

            job["current_track"] = f"{track['artist']} - {track['name']}"
            job["checked"] = i + 1

            result = await get_last_play_date(track["artist"], track["name"])

            if result == LASTFM_ERROR:
                job["errors"] += 1
            elif result is None:
                # Never scrobbled — qualifies
                qualifying.append(track)
                job["found"] = len(qualifying)
            else:
                # result is a datetime — check age
                age_days = (now - result).days
                if age_days > threshold_days:
                    qualifying.append(track)
                    job["found"] = len(qualifying)

            # Sleep between checks (except after the last one)
            if i < len(tracks) - 1:
                await asyncio.sleep(delay)

        # 5. Create new playlist with qualifying tracks
        if qualifying:
            source_info = await client.get_playlist_info(source_playlist_id)
            source_name = source_info["name"] if source_info else source_playlist_id
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            playlist_name = f"Rediscovery - {source_name} - {date_str}"
            description = (
                f"Tracks not listened to in {threshold_days}+ days. "
                f"Generated from '{source_name}'."
            )

            new_playlist = await client.create_playlist(user_id, playlist_name, description)
            if not new_playlist:
                job["status"] = "error"
                job["error_message"] = "Failed to create playlist on Spotify."
                job["finished_at"] = datetime.now(timezone.utc).isoformat()
                return

            uris = [t["uri"] for t in qualifying]
            ok = await client.add_tracks_to_playlist(new_playlist["id"], uris)
            if not ok:
                job["status"] = "error"
                job["error_message"] = "Created playlist but failed to add some tracks."
                job["result_playlist_url"] = new_playlist["url"]
                job["finished_at"] = datetime.now(timezone.utc).isoformat()
                return

            job["result_playlist_url"] = new_playlist["url"]
            logger.info("[Rediscovery] Created playlist '%s' with %d tracks", playlist_name, len(qualifying))

        job["status"] = "done"
        job["current_track"] = ""
        job["finished_at"] = datetime.now(timezone.utc).isoformat()
        logger.info("[Rediscovery] Done — %d/%d tracks qualify, %d errors",
                     len(qualifying), len(tracks), job["errors"])

    except asyncio.CancelledError:
        job["status"] = "cancelled"
        job["finished_at"] = datetime.now(timezone.utc).isoformat()
        logger.info("[Rediscovery] Task cancelled")
    except Exception as e:
        job["status"] = "error"
        job["error_message"] = str(e)
        job["finished_at"] = datetime.now(timezone.utc).isoformat()
        logger.exception("[Rediscovery] Unexpected error: %s", e)
