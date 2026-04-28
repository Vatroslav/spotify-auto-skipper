"""
Playback API routes — current track, check now, pause/resume.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.config import load_settings
from app.database import add_log
from app.routers.deps import require_auth
from app.state import app_state

router = APIRouter(prefix="/api/playback", tags=["playback"], dependencies=[Depends(require_auth)])


@router.get("")
async def get_playback(request: Request):
    """Return current track info and worker status."""
    track = app_state.current_track
    settings = await load_settings()
    return {
        "track": track,
        "skipping_paused": app_state.skipping_paused,
        "worker_running": app_state.worker_running,
        "last_checked": app_state.last_checked_timestamp.isoformat() if app_state.last_checked_timestamp else None,
        "last_check_message": app_state.last_check_message,
        "poll_interval": settings["idle_poll_interval_seconds"]
        if app_state.idle_mode
        else settings["poll_interval_seconds"],
        "idle_mode": app_state.idle_mode,
        "skip_exempt_track_id": app_state.skip_exempt_track_id,
    }


@router.post("/check-now")
async def check_now(request: Request):
    """Trigger an immediate poll cycle."""
    app_state.check_now_event.set()
    return {"ok": True}


@router.post("/skip-one-pause")
async def skip_one_pause(request: Request):
    """Exempt the currently playing song from being skipped (one-time).

    Fetches the current track directly from Spotify to ensure freshness.
    """
    client = app_state.spotify_client
    if not client:
        return JSONResponse({"ok": False, "error": "Spotify client not ready"}, status_code=503)
    track = await client.get_current_track()
    if not track or not track.get("id"):
        return JSONResponse({"ok": False, "error": "Nothing is playing"}, status_code=400)
    app_state.skip_exempt_track_id = track["id"]
    return {"ok": True, "track_name": track["name"], "artist": track["artist"]}


@router.post("/toggle-pause")
async def toggle_pause(request: Request):
    """Toggle pause/resume skipping."""
    app_state.skipping_paused = not app_state.skipping_paused
    return {"skipping_paused": app_state.skipping_paused}


@router.post("/remove-from-playlist")
async def remove_from_playlist(request: Request):
    """Remove the currently playing track from its playlist (back up to trash playlist if configured), then skip.

    Reproduces the AHK Ctrl+Media_Next workflow.
    """
    client = app_state.spotify_client
    if not client:
        return JSONResponse({"ok": False, "error": "Spotify client not ready"}, status_code=503)

    track = await client.get_current_track()
    if not track or not track.get("id"):
        return JSONResponse({"ok": False, "error": "Nothing is playing"}, status_code=400)

    context_uri = track.get("context_uri") or ""
    if not context_uri.startswith("spotify:playlist:"):
        return JSONResponse(
            {"ok": False, "error": "Currently playing track is not from a playlist"},
            status_code=400,
        )

    playlist_id = context_uri.split(":")[-1]
    track_uri = f"spotify:track:{track['id']}"
    track_label = f'"{track["name"]}" by {track["artist"]}'

    settings = await load_settings()
    trash_id = (settings.get("trash_playlist_id") or "").strip()

    # Back up to trash playlist if configured
    if trash_id:
        ok = await client.add_tracks_to_playlist(trash_id, [track_uri])
        if not ok:
            await add_log(
                f"Manual remove: failed to back up {track_label} to trash playlist {trash_id} — aborting",
                "warning",
            )
            return JSONResponse(
                {"ok": False, "error": "Failed to add to trash playlist (check trash_playlist_id)"},
                status_code=502,
            )

    # Remove from current playlist
    ok, err = await client.remove_tracks_from_playlist(playlist_id, [track_uri])
    if not ok:
        await add_log(
            f"Manual remove failed: {track_label} from playlist {playlist_id}: {err}",
            "warning",
        )
        return JSONResponse(
            {"ok": False, "error": err or "Failed to remove from playlist"},
            status_code=502,
        )

    # Skip to next, then trigger an immediate check on the new track
    await client.skip_current_track()
    app_state.check_now_event.set()

    backup_suffix = f", backed up to {trash_id}" if trash_id else ""
    await add_log(
        f"Manually removed {track_label} from playlist {playlist_id}{backup_suffix}",
        "info",
    )

    return {
        "ok": True,
        "track_name": track["name"],
        "artist": track["artist"],
        "backed_up": bool(trash_id),
    }
