"""
Never-skip artists API routes.
"""

from fastapi import APIRouter, Depends, Request

from app.database import get_never_skip_artists, add_never_skip_artist, remove_never_skip_artist
from app.config import get_spotify_client_id, get_spotify_client_secret
from app.spotify_api import SpotifyClient
from app.routers.deps import require_auth

router = APIRouter(prefix="/api/artists", tags=["artists"], dependencies=[Depends(require_auth)])


@router.get("")
async def list_artists(request: Request):
    """List all never-skip artists."""
    artists = await get_never_skip_artists()
    return {"artists": artists}


@router.post("")
async def add_artist(request: Request):
    """Add a never-skip artist."""
    body = await request.json()
    artist_id = body.get("id", "").strip()
    name = body.get("name", "").strip()
    image_url = body.get("image_url", "").strip()
    if not artist_id or not name:
        return {"error": "id and name are required"}, 400
    await add_never_skip_artist(artist_id, name, image_url)
    return {"ok": True}


@router.delete("/{artist_id}")
async def delete_artist(artist_id: str, request: Request):
    """Remove a never-skip artist."""
    await remove_never_skip_artist(artist_id)
    return {"ok": True}


@router.get("/search")
async def search_artists(request: Request, q: str = ""):
    """Search Spotify for artists."""
    if not q.strip():
        return {"artists": []}
    client = SpotifyClient(get_spotify_client_id(), get_spotify_client_secret())
    try:
        results = await client.search_artists(q, limit=5)
    finally:
        await client.close()
    return {"artists": results}
