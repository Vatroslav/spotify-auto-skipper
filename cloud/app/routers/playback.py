"""
Playback API routes — current track, check now, pause/resume.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.config import load_settings
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
