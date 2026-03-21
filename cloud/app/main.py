"""
FastAPI application entry point.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app import APP_VERSION
from app.config import get_secret_key, seed_defaults
from app.database import init_db
from app.state import app_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    await seed_defaults()

    from app.worker import polling_loop
    task = asyncio.create_task(polling_loop())
    app_state.worker_running = True

    yield

    # Shutdown
    task.cancel()
    app_state.worker_running = False
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Spotify Auto-Skipper", version=APP_VERSION, lifespan=lifespan)

# Session middleware for auth
app.add_middleware(
    SessionMiddleware,
    secret_key=get_secret_key(),
    https_only=True,
    same_site="lax",
)

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
