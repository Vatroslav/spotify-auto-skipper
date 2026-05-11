"""
Settings API routes.
"""

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.config import CONFIG_DEFAULTS, load_settings, save_settings
from app.routers.deps import require_auth
from app.spotify_api import CredentialError
from app.state import app_state

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_auth)])


class SettingsUpdate(BaseModel):
    skip_window_days: Optional[int] = None
    poll_interval_seconds: Optional[int] = None
    idle_threshold: Optional[int] = None
    idle_poll_interval_seconds: Optional[int] = None
    enable_restart_pattern: Optional[bool] = None
    restart_pattern_song_count: Optional[int] = None
    restart_pattern_day_diff: Optional[int] = None
    enable_adaptive_skip_window: Optional[bool] = None
    dummy_playlist_id: Optional[str] = None
    trash_playlist_id: Optional[str] = None
    always_play_liked_songs: Optional[bool] = None
    enable_never_skip_artists: Optional[bool] = None
    log_retention_days: Optional[int] = None


@router.get("")
async def get_settings(request: Request):
    """Return all settings."""
    settings = await load_settings()
    return settings


@router.put("")
async def update_settings(body: SettingsUpdate):
    """Partial update of settings."""
    # Only accept non-None fields that are known keys
    valid = {k: v for k, v in body.model_dump(exclude_none=True).items() if k in CONFIG_DEFAULTS}
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
        raise HTTPException(status_code=400, detail="No playlist ID or link provided")
    # Extract playlist ID from various formats
    playlist_id = q.strip()
    # Handle full URLs like https://open.spotify.com/playlist/37i9dQZF1DX0XUsuxWHRQd?si=...
    m = re.search(r"playlist/([a-zA-Z0-9]+)", playlist_id)
    if m:
        playlist_id = m.group(1)
    # Handle spotify:playlist:ID format
    if playlist_id.startswith("spotify:playlist:"):
        playlist_id = playlist_id.split(":")[-1]
    client = app_state.spotify_client
    try:
        info = await client.get_playlist_info(playlist_id)
    except CredentialError:
        raise HTTPException(status_code=401, detail="Spotify credentials expired. Please re-authorize via /auth/login.")
    if info:
        return {"id": playlist_id, **info}
    raise HTTPException(status_code=404, detail="Playlist not found")
