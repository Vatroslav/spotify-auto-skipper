"""
Shared FastAPI dependencies for API routers.
"""

from fastapi import Request, HTTPException


async def require_auth(request: Request):
    """Reject unauthenticated requests with 401."""
    if not request.session.get("authenticated", False):
        raise HTTPException(status_code=401, detail="Not authenticated")
