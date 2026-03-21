"""
Last.fm API wrapper — async version.
Nearly verbatim port from desktop app.
"""

from datetime import datetime, timezone
import logging

import httpx

from app.config import get_lastfm_username, get_lastfm_api_key
from app.spotify_api import CredentialError

logger = logging.getLogger(__name__)

# Sentinel: returned when Last.fm could not be reached (distinct from None = no scrobbles)
LASTFM_ERROR = "LASTFM_ERROR"


async def get_last_play_date(artist: str, track: str) -> datetime | str | None:
    """
    Returns:
      - datetime: last scrobble timestamp
      - None: no scrobbles found for this track
      - LASTFM_ERROR: transient/network failure (caller should not treat as "never heard")
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://ws.audioscrobbler.com/2.0/",
                params={
                    "method": "user.gettrackscrobbles",
                    "user": get_lastfm_username(),
                    "artist": artist,
                    "track": track,
                    "api_key": get_lastfm_api_key(),
                    "format": "json",
                    "limit": 1,
                },
            )
    except httpx.RequestError as e:
        logger.warning("[Last.fm] Network error: %s", e)
        return LASTFM_ERROR

    if r.status_code != 200:
        try:
            err = r.json()
            if err.get("error") == 10:
                raise CredentialError("Invalid Last.fm API key.")
        except (ValueError, KeyError):
            pass
        logger.warning("[Last.fm] Unexpected status %d: %s", r.status_code, r.text[:200])
        return LASTFM_ERROR

    data = r.json() or {}
    trackscrobbles = data.get("trackscrobbles", {})
    scrobbles = trackscrobbles.get("track")

    if not scrobbles:
        return None

    # If it's a list, take the first (latest) one
    if isinstance(scrobbles, list):
        latest = scrobbles[0]
        date_obj = latest.get("date", {})
        uts = date_obj.get("uts")
        if uts:
            try:
                return datetime.fromtimestamp(int(uts), tz=timezone.utc)
            except (ValueError, OSError):
                return None

    # If it's a single object
    if isinstance(scrobbles, dict):
        date_obj = scrobbles.get("date", {})
        uts = date_obj.get("uts")
        if uts:
            try:
                return datetime.fromtimestamp(int(uts), tz=timezone.utc)
            except (ValueError, OSError):
                return None

    return None
