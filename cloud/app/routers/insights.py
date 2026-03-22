"""
Insights API routes.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.database import get_track_events, get_track_event_dates, get_all_track_events_by_date
from app.config import load_settings
from app.insights import (
    events_from_db_rows, compute_metrics, generate_insights,
    compute_metrics_all, generate_insights_all,
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
    date_rows = await get_all_track_events_by_date(tz)
    # Convert DB rows to TrackEvent objects per date
    events_by_date = [
        (date_str, events_from_db_rows(rows))
        for date_str, rows in date_rows
    ]
    metrics = compute_metrics_all(events_by_date)
    if metrics is None:
        return {"metrics": None, "insights": []}

    settings = await load_settings()
    insights = generate_insights_all(metrics, settings["skip_window_days"])

    return {"metrics": metrics, "insights": insights}


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
