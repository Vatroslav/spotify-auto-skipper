"""
Never-skip artists API routes.
"""

import re
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from app.database import get_never_skip_artists, add_never_skip_artist, remove_never_skip_artist
from app.spotify_api import CredentialError
from app.state import app_state
from app.routers.deps import require_auth

router = APIRouter(prefix="/api/artists", tags=["artists"], dependencies=[Depends(require_auth)])

# Spotify IDs are 22-character base-62 strings
_SPOTIFY_ID_RE = re.compile(r"^[a-zA-Z0-9]{1,40}$")

_ALLOWED_IMAGE_HOSTS = {"i.scdn.co", "mosaic.scdn.co", "image-cdn-ak.spotifycdn.com",
                         "image-cdn-fa.spotifycdn.com", "wrapped-images.spotifycdn.com"}


def _validate_image_url(url: str) -> str:
    """Validate that image_url is an https Spotify CDN URL or empty."""
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_IMAGE_HOSTS:
        return ""
    return url


class ArtistCreate(BaseModel):
    id: str
    name: str
    image_url: str = ""

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        v = v.strip()
        if not _SPOTIFY_ID_RE.match(v):
            raise ValueError("Invalid Spotify artist ID")
        return v

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, v: str) -> str:
        return _validate_image_url(v.strip())


@router.get("")
async def list_artists(request: Request):
    """List all never-skip artists."""
    artists = await get_never_skip_artists()
    return {"artists": artists}


@router.post("")
async def add_artist(body: ArtistCreate):
    """Add a never-skip artist."""
    artist_id = body.id
    name = body.name.strip()
    image_url = body.image_url
    if not artist_id or not name:
        raise HTTPException(status_code=400, detail="id and name are required")
    await add_never_skip_artist(artist_id, name, image_url)
    return {"ok": True}


@router.delete("/{artist_id}")
async def delete_artist(artist_id: str, request: Request):
    """Remove a never-skip artist."""
    if not _SPOTIFY_ID_RE.match(artist_id):
        raise HTTPException(status_code=400, detail="Invalid artist ID")
    await remove_never_skip_artist(artist_id)
    return {"ok": True}


@router.get("/search")
async def search_artists(request: Request, q: str = ""):
    """Search Spotify for artists."""
    if not q.strip():
        return {"artists": []}
    client = app_state.spotify_client
    try:
        results = await client.search_artists(q, limit=5)
    except CredentialError:
        raise HTTPException(status_code=401, detail="Spotify credentials expired. Please re-authorize via /auth/login.")
    return {"artists": results}
