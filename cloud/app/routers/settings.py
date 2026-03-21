"""
Settings API routes.
"""

from fastapi import APIRouter, Request

from app.config import load_settings, save_settings, CONFIG_DEFAULTS

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def get_settings(request: Request):
    """Return all settings."""
    settings = await load_settings()
    return settings


@router.put("")
async def update_settings(request: Request):
    """Partial update of settings."""
    body = await request.json()
    # Only accept known keys
    valid = {k: v for k, v in body.items() if k in CONFIG_DEFAULTS}
    if valid:
        await save_settings(valid)
    return await load_settings()
