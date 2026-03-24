"""
Logs API routes.
"""

from fastapi import APIRouter, Depends, Request

from app.database import get_logs, get_log_dates, search_logs
from app.routers.deps import require_auth

router = APIRouter(prefix="/api/logs", tags=["logs"], dependencies=[Depends(require_auth)])


@router.get("/dates")
async def available_dates(request: Request):
    """Return list of dates with log entries."""
    dates = await get_log_dates()
    return {"dates": dates}


@router.get("/search")
async def search_log_entries(request: Request, q: str = "", date: str = "", tz: str = ""):
    """Search logs for blocks matching a song or artist query."""
    if not q.strip():
        return {"logs": []}
    logs = await search_logs(q.strip(), date, tz)
    return {"logs": logs}


@router.get("")
async def get_log_entries(
    request: Request, date: str = "", level: str = "all", tz: str = "",
    limit: int = 0, before_id: int = 0,
):
    """Return log entries for a specific date, or today if omitted."""
    logs = await get_logs(date, level, tz, limit=limit, before_id=before_id)
    has_more = bool(limit and len(logs) == limit)
    return {"date": date, "logs": logs, "has_more": has_more}
