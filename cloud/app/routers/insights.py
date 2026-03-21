"""
Insights API routes.
"""

from fastapi import APIRouter, Depends, Request

from app.database import get_track_events, get_track_event_dates
from app.config import load_settings
from app.insights import events_from_db_rows, compute_metrics, generate_insights
from app.routers.deps import require_auth

router = APIRouter(prefix="/api/insights", tags=["insights"], dependencies=[Depends(require_auth)])


@router.get("/dates")
async def available_dates(request: Request):
    """Return list of dates with track events."""
    dates = await get_track_event_dates()
    return {"dates": dates}


@router.get("")
async def get_insights(request: Request, date: str = ""):
    """Return metrics and insights for a specific date."""
    if not date:
        return {"error": "date parameter required (YYYY-MM-DD)"}, 400

    rows = await get_track_events(date)
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
