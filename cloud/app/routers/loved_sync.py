"""
Loved Sync routes — Last.fm auth flow + diff API.
"""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.config import get_base_url, get_lastfm_api_key, get_lastfm_api_secret, get_lastfm_username
from app.database import (
    add_loved_sync_ignore,
    clear_lastfm_session,
    get_lastfm_session,
    remove_loved_sync_ignore,
    save_lastfm_session,
)
from app.lastfm_api import LastfmAuthError, get_session_from_token, track_love
from app.loved_sync import compute_diff
from app.routers.deps import require_auth
from app.spotify_api import CredentialError
from app.state import app_state

router = APIRouter(tags=["loved_sync"])


# ── Last.fm web auth flow ────────────────────────────────────────


@router.get("/lastfm/auth/login", dependencies=[Depends(require_auth)])
async def lastfm_login():
    """Redirect to Last.fm's authorization page."""
    api_key = get_lastfm_api_key()
    if not api_key:
        return RedirectResponse("/sync?error=no_api_key")
    if not get_lastfm_api_secret():
        return RedirectResponse("/sync?error=no_api_secret")
    cb = f"{get_base_url()}/lastfm/auth/callback"
    params = {"api_key": api_key, "cb": cb}
    return RedirectResponse(f"https://www.last.fm/api/auth/?{urlencode(params)}")


@router.get("/lastfm/auth/callback")
async def lastfm_callback(request: Request, token: str = ""):
    """Exchange the one-time token for a session key and store it."""
    if not request.session.get("authenticated", False):
        return RedirectResponse("/")
    if not token:
        return RedirectResponse("/sync?error=no_token")

    try:
        session = await get_session_from_token(token)
    except LastfmAuthError as e:
        return RedirectResponse(f"/sync?error=auth_failed&detail={str(e)[:200]}")

    await save_lastfm_session(session["key"], session.get("name", ""))
    return RedirectResponse("/sync?authorized=1")


@router.post("/lastfm/auth/logout", dependencies=[Depends(require_auth)])
async def lastfm_logout():
    await clear_lastfm_session()
    return {"ok": True}


# ── Loved sync API ───────────────────────────────────────────────


@router.get("/api/loved-sync/status", dependencies=[Depends(require_auth)])
async def status():
    """Check whether Last.fm is authorized and creds are available."""
    session = await get_lastfm_session()
    return {
        "authorized": session is not None,
        "lastfm_username": (session or {}).get("username", "") or get_lastfm_username(),
        "has_api_secret": bool(get_lastfm_api_secret()),
    }


@router.get("/api/loved-sync/diff", dependencies=[Depends(require_auth)])
async def diff():
    """Compute the Liked-vs-Loved diff."""
    client = app_state.spotify_client
    if not client:
        raise HTTPException(status_code=503, detail="Spotify client not ready")

    username = get_lastfm_username()
    if not username:
        raise HTTPException(status_code=400, detail="LASTFM_USERNAME is not set.")

    try:
        result = await compute_diff(client, username)
    except CredentialError as e:
        raise HTTPException(status_code=401, detail=str(e))

    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error") or "Sync failed")
    return result


class LoveRequest(BaseModel):
    artist: str
    track: str


@router.post("/api/loved-sync/love", dependencies=[Depends(require_auth)])
async def love(body: LoveRequest):
    session = await get_lastfm_session()
    if not session:
        raise HTTPException(status_code=401, detail="Not authorized with Last.fm.")

    ok, err = await track_love(body.artist.strip(), body.track.strip(), session["session_key"])
    if not ok:
        raise HTTPException(status_code=502, detail=err or "Last.fm love failed")
    return {"ok": True}


class IgnoreRequest(BaseModel):
    track_id: str


@router.post("/api/loved-sync/ignore", dependencies=[Depends(require_auth)])
async def ignore(body: IgnoreRequest):
    if not body.track_id.strip():
        raise HTTPException(status_code=400, detail="track_id is required")
    await add_loved_sync_ignore(body.track_id.strip())
    return {"ok": True}


@router.post("/api/loved-sync/unignore", dependencies=[Depends(require_auth)])
async def unignore(body: IgnoreRequest):
    await remove_loved_sync_ignore(body.track_id.strip())
    return {"ok": True}
