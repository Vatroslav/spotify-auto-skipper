"""
Playback API routes — current track, check now, pause/resume.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.state import app_state

router = APIRouter(prefix="/api/playback", tags=["playback"])


@router.get("")
async def get_playback(request: Request):
    """Return current track info and worker status."""
    track = app_state.current_track
    return {
        "track": track,
        "skipping_paused": app_state.skipping_paused,
        "worker_running": app_state.worker_running,
        "last_checked": app_state.last_checked_timestamp.isoformat() if app_state.last_checked_timestamp else None,
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
