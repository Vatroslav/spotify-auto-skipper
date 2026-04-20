"""
Insights API routes.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.config import load_settings
from app.database import (
    add_track_alias,
    dismiss_mapping_fail,
    get_cached_overall_metrics,
    get_mapping_fail_candidates,
    get_track_event_dates,
    get_track_events,
    recompute_overall_metrics,
)
from app.insights import (
    compute_metrics,
    events_from_db_rows,
    generate_insights,
    generate_insights_all,
)
from app.routers.deps import require_auth

router = APIRouter(prefix="/api/insights", tags=["insights"], dependencies=[Depends(require_auth)])


@router.get("/dates")
async def available_dates(request: Request, tz: str = ""):
    """Return list of dates with track events."""
    dates = await get_track_event_dates(tz)
    return {"dates": dates}


@router.get("/overall")
async def get_overall_insights(request: Request, tz: str = ""):
    """Return aggregated metrics and insights across all dates."""
    metrics = await get_cached_overall_metrics()
    if metrics is None:
        # First run or empty cache — compute now
        await recompute_overall_metrics()
        metrics = await get_cached_overall_metrics()
    if metrics is None or metrics.get("songs_played", 0) == 0:
        return {"metrics": None, "insights": []}

    settings = await load_settings()
    insights = generate_insights_all(metrics, settings["skip_window_days"])

    return {"metrics": metrics, "insights": insights}


@router.get("/mapping-fails")
async def get_mapping_fails(request: Request):
    """Return tracks suspected of Last.fm mapping issues."""
    settings = await load_settings()
    candidates = await get_mapping_fail_candidates(settings["skip_window_days"])
    return {
        "skip_window_days": settings["skip_window_days"],
        "candidates": candidates,
    }


class DismissRequest(BaseModel):
    artist: str
    track: str


@router.post("/mapping-fails/dismiss")
async def dismiss_mapping_fail_route(payload: DismissRequest):
    """Dismiss a mapping-fail candidate until new qualifying events occur."""
    if not payload.artist or not payload.track:
        raise HTTPException(status_code=400, detail="artist and track are required")
    await dismiss_mapping_fail(payload.artist, payload.track)
    return {"ok": True}


class AliasRequest(BaseModel):
    artist: str
    spotify_name: str
    lastfm_name: str


@router.post("/track-aliases")
async def add_track_alias_route(payload: AliasRequest):
    """Upsert a Spotify-to-Last.fm track name mapping."""
    artist = payload.artist.strip()
    spotify_name = payload.spotify_name.strip()
    lastfm_name = payload.lastfm_name.strip()
    if not artist or not spotify_name or not lastfm_name:
        raise HTTPException(status_code=400, detail="artist, spotify_name, and lastfm_name are required")
    await add_track_alias(artist, spotify_name, lastfm_name)
    return {"ok": True}


@router.get("")
async def get_insights(request: Request, date: str = "", tz: str = ""):
    """Return metrics and insights for a specific date."""
    if not date:
        raise HTTPException(status_code=400, detail="date parameter required (YYYY-MM-DD)")

    rows = await get_track_events(date, tz)
    events = events_from_db_rows(rows)
    metrics = compute_metrics(events)

    settings = await load_settings()
    insights = generate_insights(metrics, settings["skip_window_days"])

    return {
        "date": date,
        "metrics": metrics,
        "insights": insights,
        "events": [
            {
                "time": e.time,
                "artist": e.artist,
                "song": e.song,
                "outcome": e.outcome,
                "days_ago": e.days_ago,
            }
            for e in events
        ],
    }
