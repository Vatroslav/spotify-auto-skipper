"""
Settings API routes.
"""

import re
from fastapi import APIRouter, Depends, Request

from app.config import load_settings, save_settings, CONFIG_DEFAULTS, get_spotify_client_id, get_spotify_client_secret
from app.spotify_api import SpotifyClient
from app.routers.deps import require_auth

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_auth)])


@router.get("")
async def get_settings(request: Request):
    """Return all settings."""
    settings = await load_settings()
    return settings


@router.put("")
async def update_settings(request: Request):
    """Partial update of settings."""
    body = await request.json()
    # Only accept known keys
    valid = {k: v for k, v in body.items() if k in CONFIG_DEFAULTS}
    warnings = []
    if valid:
        warnings = await save_settings(valid)
    settings = await load_settings()
    settings["_warnings"] = warnings
    return settings


@router.get("/resolve-playlist")
async def resolve_playlist(request: Request, q: str = ""):
    """Resolve a Spotify playlist link or ID to its name."""
    if not q.strip():
        return {"error": "No playlist ID or link provided"}
    # Extract playlist ID from various formats
    playlist_id = q.strip()
    # Handle full URLs like https://open.spotify.com/playlist/37i9dQZF1DX0XUsuxWHRQd?si=...
    m = re.search(r"playlist/([a-zA-Z0-9]+)", playlist_id)
    if m:
        playlist_id = m.group(1)
    # Handle spotify:playlist:ID format
    if playlist_id.startswith("spotify:playlist:"):
        playlist_id = playlist_id.split(":")[-1]
    client = SpotifyClient(get_spotify_client_id(), get_spotify_client_secret())
    try:
        info = await client.get_playlist_info(playlist_id)
    finally:
        await client.close()
    if info:
        return {"id": playlist_id, **info}
    return {"error": "Playlist not found"}
