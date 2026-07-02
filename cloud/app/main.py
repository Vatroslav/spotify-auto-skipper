"""
FastAPI application entry point.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app import APP_VERSION
from app.config import (
    get_allow_any_spotify_user,
    get_allowed_spotify_user,
    get_secret_key,
    get_spotify_client_id,
    get_spotify_client_secret,
    seed_defaults,
)
from app.database import init_db
from app.spotify_api import SpotifyClient
from app.state import app_state

_startup_log = logging.getLogger("startup")


def _log_auth_posture() -> None:
    """Warn loudly at startup about who is allowed to log in."""
    if get_allowed_spotify_user():
        _startup_log.info("Login restricted to Spotify user '%s'.", get_allowed_spotify_user())
    elif get_allow_any_spotify_user():
        _startup_log.warning(
            "ALLOW_ANY_SPOTIFY_USER is enabled: ANY Spotify account can log in and take over "
            "this instance. Set ALLOWED_SPOTIFY_USER to your Spotify user ID to lock it down."
        )
    else:
        _startup_log.warning(
            "ALLOWED_SPOTIFY_USER is not set — login is disabled (fail-closed). Set "
            "ALLOWED_SPOTIFY_USER to your Spotify user ID, or set ALLOW_ANY_SPOTIFY_USER=true "
            "to intentionally allow open login."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    await seed_defaults()
    _log_auth_posture()

    # Create a single shared SpotifyClient for the entire process
    app_state.spotify_client = SpotifyClient(get_spotify_client_id(), get_spotify_client_secret())

    from app.worker import polling_loop

    app_state.worker_task = asyncio.create_task(polling_loop())
    app_state.worker_running = True

    yield

    # Shutdown
    if app_state.worker_task:
        app_state.worker_task.cancel()
    app_state.worker_running = False
    try:
        if app_state.worker_task:
            await app_state.worker_task
    except asyncio.CancelledError:
        pass
    if app_state.spotify_client:
        await app_state.spotify_client.close()
        app_state.spotify_client = None


app = FastAPI(title="Spotify Auto-Skipper", version=APP_VERSION, lifespan=lifespan)

# Session middleware for auth
app.add_middleware(
    SessionMiddleware,
    secret_key=get_secret_key(),
    https_only=True,
    same_site="lax",
)


# Content Security Policy middleware
class CSPMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' https://i.scdn.co https://mosaic.scdn.co https://image-cdn-ak.spotifycdn.com "
            "https://image-cdn-fa.spotifycdn.com https://wrapped-images.spotifycdn.com; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; "
            "connect-src 'self'"
        )
        return response


app.add_middleware(CSPMiddleware)

# Static files and templates
import mimetypes
import os

# Ensure the web manifest is served with the correct content type by StaticFiles
mimetypes.add_type("application/manifest+json", ".webmanifest")

_app_dir = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(_app_dir, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(_app_dir, "templates"))

# Service worker must be served from the root so its scope covers the whole app.
# The cache name is templated with APP_VERSION so each deploy busts the old cache.
_sw_path = os.path.join(_app_dir, "static", "js", "sw.js")


@app.get("/sw.js")
async def service_worker():
    with open(_sw_path, encoding="utf-8") as f:
        body = f.read().replace("{{VERSION}}", APP_VERSION)
    return Response(
        content=body,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )

# Include routers
from app.routers import artists, auth, insights, logs, loved_sync, playback, rediscovery, settings

app.include_router(auth.router)
app.include_router(playback.router)
app.include_router(settings.router)
app.include_router(artists.router)
app.include_router(insights.router)
app.include_router(logs.router)
app.include_router(rediscovery.router)
app.include_router(loved_sync.router)


# ── Health check ─────────────────────────────────────────────────


@app.get("/health")
async def health():
    worker_alive = app_state.worker_task is not None and not app_state.worker_task.done()
    body = {
        "status": "ok" if worker_alive else "degraded",
        "version": APP_VERSION,
        "worker_running": app_state.worker_running,
        "worker_alive": worker_alive,
    }
    status_code = 200 if worker_alive else 503
    return JSONResponse(content=body, status_code=status_code)


# ── Page routes ──────────────────────────────────────────────────


def _is_authenticated(request: Request) -> bool:
    return request.session.get("authenticated", False)


@app.get("/")
async def index(request: Request):
    if not _is_authenticated(request):
        return templates.TemplateResponse("login.html", {"request": request, "version": APP_VERSION})
    return templates.TemplateResponse("index.html", {"request": request, "version": APP_VERSION})


@app.get("/settings")
async def settings_page(request: Request):
    if not _is_authenticated(request):
        return templates.TemplateResponse("login.html", {"request": request, "version": APP_VERSION})
    return templates.TemplateResponse("settings.html", {"request": request, "version": APP_VERSION})


@app.get("/artists")
async def artists_page(request: Request):
    if not _is_authenticated(request):
        return templates.TemplateResponse("login.html", {"request": request, "version": APP_VERSION})
    return templates.TemplateResponse("artists.html", {"request": request, "version": APP_VERSION})


@app.get("/insights")
async def insights_page(request: Request):
    if not _is_authenticated(request):
        return templates.TemplateResponse("login.html", {"request": request, "version": APP_VERSION})
    return templates.TemplateResponse("insights.html", {"request": request, "version": APP_VERSION})


@app.get("/logs")
async def logs_page(request: Request):
    if not _is_authenticated(request):
        return templates.TemplateResponse("login.html", {"request": request, "version": APP_VERSION})
    return templates.TemplateResponse("logs.html", {"request": request, "version": APP_VERSION})


@app.get("/rediscovery")
async def rediscovery_page(request: Request):
    if not _is_authenticated(request):
        return templates.TemplateResponse("login.html", {"request": request, "version": APP_VERSION})
    return templates.TemplateResponse("rediscovery.html", {"request": request, "version": APP_VERSION})


@app.get("/sync")
async def sync_page(request: Request):
    if not _is_authenticated(request):
        return templates.TemplateResponse("login.html", {"request": request, "version": APP_VERSION})
    return templates.TemplateResponse("loved_sync.html", {"request": request, "version": APP_VERSION})


@app.get("/unauthorized")
async def unauthorized_page(request: Request):
    return templates.TemplateResponse("unauthorized.html", {"request": request, "version": APP_VERSION})
