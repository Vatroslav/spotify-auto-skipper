"""
Rediscovery Playlist API routes.
"""

import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.rediscovery import run_rediscovery, _default_job
from app.routers.deps import require_auth
from app.state import app_state

router = APIRouter(prefix="/api/rediscovery", tags=["rediscovery"], dependencies=[Depends(require_auth)])


class StartRequest(BaseModel):
    playlist_url: str
    threshold_days: int = 60
    hours_available: float = 8.0
    output_name: str | None = None


def _parse_playlist_id(raw: str) -> str:
    """Extract playlist ID from URL, URI, or bare ID."""
    raw = raw.strip()
    m = re.search(r"playlist/([a-zA-Z0-9]+)", raw)
    if m:
        return m.group(1)
    if raw.startswith("spotify:playlist:"):
        return raw.split(":")[-1]
    return raw


@router.post("/start")
async def start(body: StartRequest):
    playlist_id = _parse_playlist_id(body.playlist_url)
    if not playlist_id:
        raise HTTPException(status_code=400, detail="Invalid playlist URL or ID.")
    if body.threshold_days < 1:
        raise HTTPException(status_code=400, detail="Threshold must be at least 1 day.")
    if body.hours_available < 0.1:
        raise HTTPException(status_code=400, detail="Hours available must be at least 0.1.")

    # Don't start if already running
    if app_state.rediscovery_job and app_state.rediscovery_job["status"] == "running":
        raise HTTPException(status_code=409, detail="A rediscovery job is already running.")

    app_state.rediscovery_job = _default_job()
    app_state.rediscovery_task = asyncio.create_task(
        run_rediscovery(playlist_id, body.threshold_days, body.hours_available, body.output_name)
    )
    return {"ok": True}


@router.get("/status")
async def status():
    if not app_state.rediscovery_job:
        return {"status": "idle"}
    return app_state.rediscovery_job


@router.post("/cancel")
async def cancel():
    if not app_state.rediscovery_job or app_state.rediscovery_job["status"] != "running":
        raise HTTPException(status_code=400, detail="No running job to cancel.")
    app_state.rediscovery_job["status"] = "cancelled"
    if app_state.rediscovery_task and not app_state.rediscovery_task.done():
        app_state.rediscovery_task.cancel()
    return {"ok": True}
