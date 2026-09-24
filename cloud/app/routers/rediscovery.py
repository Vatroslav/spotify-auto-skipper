"""
Rediscovery API routes.
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.rediscovery import DEFAULT_THRESHOLD_DAYS, MAX_THRESHOLDS, run_cleanup_job, run_rediscovery_job
from app.routers.deps import require_auth
from app.spotify_api import CredentialError, SpotifyAPIError
from app.state import app_state

router = APIRouter(prefix="/api/rediscovery", tags=["rediscovery"], dependencies=[Depends(require_auth)])


class StartRequest(BaseModel):
    playlist_id: str
    playlist_name: str
    thresholds_days: list[Annotated[int, Field(ge=1, le=36500)]] = Field(
        default_factory=lambda: [DEFAULT_THRESHOLD_DAYS], min_length=1, max_length=MAX_THRESHOLDS
    )


@router.get("/playlists")
async def list_playlists():
    """Return user's Spotify playlists for the dropdown."""
    client = app_state.spotify_client
    if not client:
        raise HTTPException(status_code=503, detail="Spotify client not ready")
    try:
        playlists = await client.get_user_playlists()
    except CredentialError:
        raise HTTPException(status_code=401, detail="Spotify credentials expired.")
    except SpotifyAPIError as e:
        raise HTTPException(status_code=502, detail=f"Could not load playlists from Spotify: {e}")
    return {"playlists": playlists}


@router.get("/status")
async def get_status():
    """Return current rediscovery job status."""
    return {
        "status": app_state.rediscovery_status,
        "progress": app_state.rediscovery_progress,
        "playlists": app_state.rediscovery_playlists,
        "result_count": len(app_state.rediscovery_results),
    }


@router.post("/start")
async def start_job(body: StartRequest):
    """Start a rediscovery background job."""
    # Don't allow concurrent jobs
    if app_state.rediscovery_status == "running":
        raise HTTPException(status_code=409, detail="A job is already running.")

    if not body.playlist_id.strip():
        raise HTTPException(status_code=400, detail="playlist_id is required.")

    playlist_name = body.playlist_name.strip() or "Rediscovery"

    # Reset state
    app_state.rediscovery_results = []
    app_state.rediscovery_playlists = []
    app_state.rediscovery_status = "running"
    app_state.rediscovery_progress = {}

    # Spawn background task
    app_state.rediscovery_task = asyncio.create_task(
        run_rediscovery_job(app_state, body.playlist_id.strip(), playlist_name, sorted(set(body.thresholds_days)))
    )

    return {"ok": True}


@router.post("/cleanup")
async def start_cleanup():
    """Start removing listened and unavailable tracks from all Rediscovery playlists.

    Shares the scan's job slot, status and cancel: one job at a time keeps
    Last.fm under its rate limit.
    """
    if app_state.rediscovery_status == "running":
        raise HTTPException(status_code=409, detail="A job is already running.")
    if not app_state.spotify_client:
        raise HTTPException(status_code=503, detail="Spotify client not ready")

    app_state.rediscovery_results = []
    app_state.rediscovery_playlists = []
    app_state.rediscovery_status = "running"
    app_state.rediscovery_progress = {}

    app_state.rediscovery_task = asyncio.create_task(run_cleanup_job(app_state))

    return {"ok": True}


@router.post("/cancel")
async def cancel_job():
    """Cancel a running rediscovery job."""
    if app_state.rediscovery_task and not app_state.rediscovery_task.done():
        app_state.rediscovery_task.cancel()
        return {"ok": True}
    raise HTTPException(status_code=400, detail="No running job to cancel.")
