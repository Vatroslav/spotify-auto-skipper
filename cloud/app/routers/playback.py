"""
Playback API routes — current track, check now, pause/resume.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.state import app_state
from app.config import load_settings
from app.routers.deps import require_auth

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
        "poll_interval": settings["idle_poll_interval_seconds"] if app_state.idle_mode else settings["poll_interval_seconds"],
        "idle_mode": app_state.idle_mode,
    }


@router.post("/check-now")
async def check_now(request: Request):
    """Trigger an immediate poll cycle."""
    app_state.check_now_event.set()
    return {"ok": True}


@router.post("/toggle-pause")
async def toggle_pause(request: Request):
    """Toggle pause/resume skipping."""
    app_state.skipping_paused = not app_state.skipping_paused
    return {"skipping_paused": app_state.skipping_paused}
