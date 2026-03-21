"""
Never-skip artists API routes.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.database import get_never_skip_artists, add_never_skip_artist, remove_never_skip_artist
from app.config import get_spotify_client_id, get_spotify_client_secret
from app.spotify_api import SpotifyClient
from app.routers.deps import require_auth

router = APIRouter(prefix="/api/artists", tags=["artists"], dependencies=[Depends(require_auth)])


class ArtistCreate(BaseModel):
    id: str
    name: str
    image_url: str = ""


@router.get("")
async def list_artists(request: Request):
    """List all never-skip artists."""
    artists = await get_never_skip_artists()
    return {"artists": artists}


@router.post("")
async def add_artist(body: ArtistCreate):
    """Add a never-skip artist."""
    artist_id = body.id.strip()
    name = body.name.strip()
    image_url = body.image_url.strip()
    if not artist_id or not name:
        raise HTTPException(status_code=400, detail="id and name are required")
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
