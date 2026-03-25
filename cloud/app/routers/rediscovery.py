"""
Rediscovery API routes.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.spotify_api import CredentialError
from app.state import app_state
from app.routers.deps import require_auth

router = APIRouter(prefix="/api/rediscovery", tags=["rediscovery"], dependencies=[Depends(require_auth)])


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
    return {"playlists": playlists}


@router.get("/status")
async def get_status():
    """Return current rediscovery job status."""
    return {
        "status": app_state.rediscovery_status,
        "progress": app_state.rediscovery_progress,
        "playlist_url": app_state.rediscovery_playlist_url,
        "result_count": len(app_state.rediscovery_results),
    }
