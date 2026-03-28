"""
Spotify OAuth Authorization Code Flow.
"""

import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
import httpx

from app.config import get_spotify_client_id, get_spotify_client_secret, get_base_url, get_allowed_spotify_user
from app.database import save_oauth_tokens, clear_oauth_tokens
from app.routers.deps import require_auth
from app.state import app_state
from datetime import datetime, timedelta, timezone

router = APIRouter(tags=["auth"])

SCOPES = "user-read-currently-playing user-read-playback-state user-modify-playback-state user-library-read playlist-read-private playlist-modify-private"


@router.get("/auth/login")
async def login(request: Request):
    """Redirect to Spotify's authorization page."""
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state

    params = {
        "client_id": get_spotify_client_id(),
        "response_type": "code",
        "redirect_uri": f"{get_base_url()}/auth/callback",
        "scope": SCOPES,
        "state": state,
    }
    return RedirectResponse(f"https://accounts.spotify.com/authorize?{urlencode(params)}")


@router.get("/auth/callback")
async def callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """Handle Spotify's OAuth callback."""
    if error:
        return RedirectResponse("/?error=auth_denied")

    # Verify state
    expected_state = request.session.get("oauth_state")
    if not expected_state or state != expected_state:
        return RedirectResponse("/?error=invalid_state")

    # Exchange code for tokens
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://accounts.spotify.com/api/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": f"{get_base_url()}/auth/callback",
                    "client_id": get_spotify_client_id(),
                    "client_secret": get_spotify_client_secret(),
                },
            )
    except httpx.RequestError:
        return RedirectResponse("/?error=spotify_unreachable")

    if r.status_code != 200:
        return RedirectResponse("/?error=token_exchange_failed")

    try:
        data = r.json()
    except (ValueError, KeyError):
        return RedirectResponse("/?error=invalid_token_response")

    access_token = data.get("access_token")
    if not access_token:
        return RedirectResponse("/?error=missing_access_token")
    refresh_token = data.get("refresh_token", "")
    try:
        expires_in = int(data.get("expires_in", 3600))
    except (ValueError, TypeError):
        expires_in = 3600
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(0, expires_in - 100))

    # Check if the logged-in user is allowed
    allowed_user = get_allowed_spotify_user()
    if allowed_user:
        try:
            async with httpx.AsyncClient(timeout=10) as me_client:
                me_resp = await me_client.get(
                    "https://api.spotify.com/v1/me",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            if me_resp.status_code == 200:
                spotify_user_id = me_resp.json().get("id", "")
                if spotify_user_id != allowed_user:
                    return RedirectResponse("/unauthorized")
            else:
                import logging
                logging.getLogger("auth").warning(
                    "Spotify /v1/me returned %s: %s", me_resp.status_code, me_resp.text[:200]
                )
                return RedirectResponse("/unauthorized")
        except httpx.RequestError:
            return RedirectResponse("/unauthorized")

    await save_oauth_tokens(access_token, refresh_token, expires_at.isoformat())

    request.session["authenticated"] = True
    request.session.pop("oauth_state", None)

    # Restart the worker if it died from a previous CredentialError
    app_state.restart_worker_if_dead()

    return RedirectResponse("/")


@router.post("/auth/logout", dependencies=[Depends(require_auth)])
async def logout(request: Request):
    """End session, clear stored OAuth tokens, and reset the shared client."""
    request.session.clear()
    await clear_oauth_tokens()
    # Reset the shared client's in-memory token so it stops working immediately
    if app_state.spotify_client:
        app_state.spotify_client._access_token = None
        app_state.spotify_client._token_expires_at = datetime.now(timezone.utc)
    return {"ok": True}
