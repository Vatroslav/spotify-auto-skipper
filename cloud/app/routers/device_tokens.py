"""
Device token management — long-lived bearer tokens for the Android Auto controller.

Session-only by design: a device token authenticates playback commands, but
issuing, listing and revoking tokens requires a real browser login.
"""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.config import get_base_url
from app.database import add_device_token, add_log, delete_device_token, get_device_tokens
from app.routers.deps import hash_device_token, require_auth

router = APIRouter(prefix="/api/device-tokens", tags=["device-tokens"], dependencies=[Depends(require_auth)])

MAX_LABEL_LEN = 60


class DeviceTokenCreate(BaseModel):
    label: str = ""


@router.get("")
async def list_device_tokens(request: Request):
    """List issued device tokens (metadata only — the token itself is not stored)."""
    return {"tokens": await get_device_tokens()}


@router.post("")
async def create_device_token(body: DeviceTokenCreate):
    """Issue a device token. The plaintext value is returned exactly once."""
    label = body.label.strip()[:MAX_LABEL_LEN]
    token = secrets.token_urlsafe(32)
    row = await add_device_token(hash_device_token(token), label)
    await add_log(f"Device token issued: {label or 'unnamed'} (id {row['id']})", "info")
    # base_url comes from the server config so the QR carries the public URL
    # even when the PWA is open on some other host name.
    return {**row, "token": token, "base_url": get_base_url()}


@router.delete("/{token_id}")
async def revoke_device_token(token_id: int):
    """Revoke a device token."""
    deleted = await delete_device_token(token_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Device token not found")
    await add_log(f"Device token revoked (id {token_id})", "info")
    return {"ok": True}
