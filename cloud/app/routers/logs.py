"""
Logs API routes.
"""

from fastapi import APIRouter, Depends, Request

from app.database import get_logs, get_log_dates
from app.routers.deps import require_auth

router = APIRouter(prefix="/api/logs", tags=["logs"], dependencies=[Depends(require_auth)])


@router.get("/dates")
async def available_dates(request: Request):
    """Return list of dates with log entries."""
    dates = await get_log_dates()
    return {"dates": dates}


@router.get("")
async def get_log_entries(request: Request, date: str = "", level: str = "all"):
    """Return log entries for a specific date."""
    if not date:
        return {"error": "date parameter required (YYYY-MM-DD)"}, 400

    logs = await get_logs(date, level)
    return {"date": date, "logs": logs}
