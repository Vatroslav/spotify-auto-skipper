"""
Playlist genre mix API routes.

The analysis runs as a background job rather than inside the request. The
Last.fm source needs one call per artist (no batch endpoint exists), which is
minutes on a cold cache — far past any sane request timeout. The Spotify source
is much faster but goes through the same path so there is one flow, one
progress bar, and no request that quietly grows past its timeout as a playlist
grows.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.genre_stats import SOURCE_SPOTIFY, SOURCES, compute_genre_stats
from app.observability import report_exception
from app.routers.deps import require_auth
from app.spotify_api import CredentialError, SpotifyAPIError
from app.state import app_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/genres", tags=["genres"], dependencies=[Depends(require_auth)])


class StartRequest(BaseModel):
    playlist_id: str
    source: str = SOURCE_SPOTIFY


@router.get("/playlists")
async def list_playlists():
    """Return the user's Spotify playlists for the dropdown."""
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


async def run_genre_job(playlist_id: str, source: str):
    """Compute the genre mix and park the result in app_state."""

    def progress(current: int, total: int, message: str):
        app_state.genres_progress = {"current": current, "total": total, "message": message}

    try:
        result = await compute_genre_stats(
            app_state.spotify_client, playlist_id, source=source, progress=progress
        )
        app_state.genres_result = result
        app_state.genres_status = "completed"
        app_state.genres_progress = {
            "current": result["artist_count"],
            "total": result["artist_count"],
            "message": f"Done. {len(result['genres'])} genres across {result['artist_count']} artists.",
        }
        logger.info(
            "[Genres] %s scan done: %d genres, %d artists, %d tracks",
            source,
            len(result["genres"]),
            result["artist_count"],
            result["total_tracks"],
        )
    except asyncio.CancelledError:
        app_state.genres_status = "idle"
        app_state.genres_progress = {"message": "Cancelled."}
        logger.info("[Genres] Job cancelled.")
        raise
    except (CredentialError, SpotifyAPIError) as e:
        app_state.genres_status = "failed"
        app_state.genres_progress = {"message": f"Spotify: {e}"}
        logger.warning("[Genres] Job failed: %s", e)
    except Exception as e:
        app_state.genres_status = "failed"
        app_state.genres_progress = {"message": f"Error: {e}"}
        logger.exception("[Genres] Job failed: %s", e)
        report_exception(e, component="genres")


@router.post("/start")
async def start_job(body: StartRequest):
    """Start a genre analysis job."""
    if app_state.genres_status == "running":
        raise HTTPException(status_code=409, detail="A genre scan is already running.")
    if not body.playlist_id.strip():
        raise HTTPException(status_code=400, detail="playlist_id is required.")
    if body.source not in SOURCES:
        raise HTTPException(status_code=400, detail=f"source must be one of {', '.join(SOURCES)}")
    if not app_state.spotify_client:
        raise HTTPException(status_code=503, detail="Spotify client not ready")

    app_state.genres_result = None
    app_state.genres_status = "running"
    app_state.genres_progress = {"current": 0, "total": 0, "message": "Starting..."}
    app_state.genres_task = asyncio.create_task(run_genre_job(body.playlist_id.strip(), body.source))
    return {"ok": True}


@router.get("/status")
async def get_status():
    """Return the current job status, plus the result once it is done."""
    return {
        "status": app_state.genres_status,
        "progress": app_state.genres_progress,
        "result": app_state.genres_result,
    }


@router.post("/cancel")
async def cancel_job():
    """Cancel a running genre analysis job."""
    if app_state.genres_task and not app_state.genres_task.done():
        app_state.genres_task.cancel()
        return {"ok": True}
    raise HTTPException(status_code=400, detail="No running job to cancel.")
