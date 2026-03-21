"""
FastAPI application entry point.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app import APP_VERSION
from app.config import get_secret_key, get_spotify_client_id, get_spotify_client_secret, seed_defaults
from app.database import init_db
from app.spotify_api import SpotifyClient
from app.state import app_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    await seed_defaults()

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
import os
_app_dir = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(_app_dir, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(_app_dir, "templates"))

# Include routers
from app.routers import auth, playback, settings, artists, insights, logs

app.include_router(auth.router)
app.include_router(playback.router)
app.include_router(settings.router)
app.include_router(artists.router)
app.include_router(insights.router)
app.include_router(logs.router)


# ── Health check ─────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "worker_running": app_state.worker_running,
        "worker_alive": app_state.worker_task is not None and not app_state.worker_task.done(),
    }


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
