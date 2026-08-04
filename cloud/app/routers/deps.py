"""
Shared FastAPI dependencies for API routers.
"""

import hashlib
import hmac

from fastapi import HTTPException, Request

from app.database import add_log, get_device_token_hashes, touch_device_token


async def require_auth(request: Request):
    """Reject unauthenticated requests with 401."""
    if not request.session.get("authenticated", False):
        raise HTTPException(status_code=401, detail="Not authenticated")


def hash_device_token(token: str) -> str:
    """Hash a device token for storage and comparison. Shared with the issuer."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _match_device_token(token: str) -> int | None:
    """Return the id of the device token matching `token`, or None.

    Every stored hash is compared with hmac.compare_digest so a wrong token
    can't be narrowed down by timing.
    """
    candidate = hash_device_token(token)
    matched: int | None = None
    for token_id, stored_hash in await get_device_token_hashes():
        if hmac.compare_digest(candidate, stored_hash or ""):
            matched = token_id
    return matched


async def require_auth_or_device_token(request: Request):
    """Allow a browser session OR a valid device token (Authorization: Bearer).

    Used only by the playback router — the manual commands the Android Auto
    controller needs. Everything else stays session-only, so a leaked device
    token can send playback commands and nothing more.
    """
    if request.session.get("authenticated", False):
        return

    scheme, _, raw_token = request.headers.get("Authorization", "").partition(" ")
    token = raw_token.strip()
    if scheme.lower() == "bearer" and token:
        token_id = await _match_device_token(token)
        if token_id is not None:
            await touch_device_token(token_id)
            request.state.device_token_id = token_id
            return
        # Log the attempt, never the token itself.
        client_host = request.client.host if request.client else "unknown"
        await add_log(
            f"Device token auth failed: unknown token from {client_host} for {request.url.path}",
            "warning",
        )

    raise HTTPException(status_code=401, detail="Not authenticated")
