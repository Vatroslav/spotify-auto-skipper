"""
Playlist genre mix API routes.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.genre_stats import compute_genre_stats
from app.routers.deps import require_auth
from app.spotify_api import CredentialError, SpotifyAPIError
from app.state import app_state

router = APIRouter(prefix="/api/genres", tags=["genres"], dependencies=[Depends(require_auth)])


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


@router.get("/stats")
async def stats(playlist_id: str = ""):
    """Return the genre breakdown of one playlist."""
    client = app_state.spotify_client
    if not client:
        raise HTTPException(status_code=503, detail="Spotify client not ready")
    if not playlist_id.strip():
        raise HTTPException(status_code=400, detail="playlist_id is required.")

    try:
        return await compute_genre_stats(client, playlist_id.strip())
    except CredentialError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except SpotifyAPIError as e:
        raise HTTPException(status_code=502, detail=f"Spotify: {e}")
