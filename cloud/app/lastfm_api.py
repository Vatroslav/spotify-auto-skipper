"""
Last.fm API wrapper — async version.
Nearly verbatim port from desktop app.
"""

import hashlib
import logging
from datetime import datetime, timezone

import httpx

from app.config import get_lastfm_api_key, get_lastfm_api_secret, get_lastfm_username
from app.spotify_api import CredentialError

logger = logging.getLogger(__name__)

LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"

# Sentinel: returned when Last.fm could not be reached (distinct from None = no scrobbles)
LASTFM_ERROR = "LASTFM_ERROR"


class LastfmAuthError(Exception):
    """Raised when Last.fm auth/signing operations fail."""


def _sign(params: dict) -> str:
    """Compute api_sig: md5(concat of sorted-key params + api_secret).

    Per Last.fm docs: omit `format` and `callback` from the signature input.
    """
    secret = get_lastfm_api_secret()
    if not secret:
        raise LastfmAuthError("LASTFM_API_SECRET is not set.")
    keys = sorted(k for k in params if k not in ("format", "callback"))
    raw = "".join(f"{k}{params[k]}" for k in keys) + secret
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


async def _lookup_scrobbles(artist: str, track: str) -> datetime | str | None:
    """
    Raw scrobble lookup — no fallback logic.
    Returns datetime, None (no scrobbles), or LASTFM_ERROR.
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


async def get_last_play_date(artist: str, track: str, track_id: str = "") -> datetime | str | None:
    """
    Returns:
      - datetime: last scrobble timestamp
      - None: no scrobbles found for this track
      - LASTFM_ERROR: transient/network failure (caller should not treat as "never heard")

    If the track has a user-defined alias in track_aliases, that alias takes
    priority over the original Spotify name (handles cases where Last.fm
    scrobbles the track under a different name than Spotify reports).

    Aliases are keyed primarily by Spotify track_id. If no id-keyed alias
    exists, falls back to (artist, track) matching for legacy rows.
    """
    from app.database import get_track_alias

    alias = await get_track_alias(track_id, artist, track)
    if alias:
        logger.info("[Last.fm] Using alias: '%s' → '%s'", track, alias)
        return await _lookup_scrobbles(artist, alias)

    return await _lookup_scrobbles(artist, track)


# ── Now playing (read) ───────────────────────────────────────────


async def get_nowplaying(username: str = "") -> dict | None:
    """Return the user's currently-scrobbling track, or None if nothing live.

    Last.fm's `user.getRecentTracks` puts the live track first with
    `@attr.nowplaying == "true"`. If the first item is just a recent scrobble
    (has a `date` field), there is nothing currently playing.

    Returns {"artist": str, "name": str} or None. Network/HTTP failures also
    map to None — caller treats absence as "no signal" rather than an error.
    """
    user = username or get_lastfm_username()
    if not user:
        return None
    api_key = get_lastfm_api_key()
    if not api_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                LASTFM_API_URL,
                params={
                    "method": "user.getrecenttracks",
                    "user": user,
                    "api_key": api_key,
                    "format": "json",
                    "limit": 1,
                },
            )
    except httpx.RequestError as e:
        logger.warning("[Last.fm] Network error fetching nowplaying: %s", e)
        return None

    if r.status_code != 200:
        logger.warning("[Last.fm] getRecentTracks status %d: %s", r.status_code, r.text[:200])
        return None

    try:
        data = r.json() or {}
    except ValueError:
        return None

    tracks = (data.get("recenttracks") or {}).get("track") or []
    if isinstance(tracks, dict):
        tracks = [tracks]
    if not tracks:
        return None

    first = tracks[0]
    attr = first.get("@attr") or {}
    if str(attr.get("nowplaying", "")).lower() != "true":
        return None

    artist_obj = first.get("artist") or {}
    artist_name = artist_obj.get("#text") if isinstance(artist_obj, dict) else str(artist_obj)
    name = first.get("name", "")
    if not artist_name or not name:
        return None
    return {"artist": artist_name, "name": name}


# ── Recent tracks (read) ─────────────────────────────────────────


async def get_recent_tracks(from_uts: int, to_uts: int, username: str = "") -> list[dict] | str:
    """Return scrobbles with a UTS in [from_uts, to_uts], paginated.

    Each entry: {"artist": str, "name": str, "uts": int}. The live nowplaying
    entry (which has no `date`) is skipped. Returns LASTFM_ERROR on failure.
    """
    user = username or get_lastfm_username()
    if not user:
        return []
    api_key = get_lastfm_api_key()
    if not api_key:
        return []

    results: list[dict] = []
    page = 1
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                r = await client.get(
                    LASTFM_API_URL,
                    params={
                        "method": "user.getrecenttracks",
                        "user": user,
                        "api_key": api_key,
                        "format": "json",
                        "limit": 200,
                        "page": page,
                        "from": from_uts,
                        "to": to_uts,
                    },
                )
                if r.status_code != 200:
                    logger.warning(
                        "[Last.fm] getRecentTracks status %d: %s", r.status_code, r.text[:200]
                    )
                    return LASTFM_ERROR
                data = r.json() or {}
                rt = data.get("recenttracks", {})
                tracks = rt.get("track", [])
                if isinstance(tracks, dict):
                    tracks = [tracks]
                for t in tracks:
                    attr = t.get("@attr") or {}
                    if str(attr.get("nowplaying", "")).lower() == "true":
                        continue  # live track, not a completed scrobble
                    artist_obj = t.get("artist") or {}
                    artist_name = (
                        artist_obj.get("#text") if isinstance(artist_obj, dict) else str(artist_obj)
                    )
                    name = t.get("name", "")
                    date_obj = t.get("date") or {}
                    uts_raw = date_obj.get("uts") if isinstance(date_obj, dict) else None
                    try:
                        uts = int(uts_raw) if uts_raw else None
                    except (ValueError, TypeError):
                        uts = None
                    if artist_name and name and uts is not None:
                        results.append({"artist": artist_name, "name": name, "uts": uts})

                attr = rt.get("@attr", {})
                try:
                    total_pages = int(attr.get("totalPages", 1))
                except (ValueError, TypeError):
                    total_pages = 1
                if page >= total_pages:
                    break
                page += 1
    except httpx.RequestError as e:
        logger.warning("[Last.fm] Network error fetching recent tracks: %s", e)
        return LASTFM_ERROR

    return results


# ── Loved tracks (read) ──────────────────────────────────────────


async def get_loved_tracks(username: str = "") -> list[dict] | str:
    """Return all loved tracks for the user (paginated). Returns LASTFM_ERROR on failure.

    Each entry: {"artist": str, "name": str, "uts": int|None}.
    """
    user = username or get_lastfm_username()
    if not user:
        return []

    results: list[dict] = []
    page = 1
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                r = await client.get(
                    LASTFM_API_URL,
                    params={
                        "method": "user.getlovedtracks",
                        "user": user,
                        "api_key": get_lastfm_api_key(),
                        "format": "json",
                        "limit": 200,
                        "page": page,
                    },
                )
                if r.status_code != 200:
                    logger.warning("[Last.fm] getLovedTracks status %d: %s", r.status_code, r.text[:200])
                    return LASTFM_ERROR
                data = r.json() or {}
                loved = data.get("lovedtracks", {})
                tracks = loved.get("track", [])
                if isinstance(tracks, dict):
                    tracks = [tracks]
                for t in tracks:
                    artist_obj = t.get("artist") or {}
                    artist_name = artist_obj.get("name") if isinstance(artist_obj, dict) else str(artist_obj)
                    name = t.get("name", "")
                    date_obj = t.get("date") or {}
                    uts_raw = date_obj.get("uts") if isinstance(date_obj, dict) else None
                    try:
                        uts = int(uts_raw) if uts_raw else None
                    except (ValueError, TypeError):
                        uts = None
                    if artist_name and name:
                        results.append({"artist": artist_name, "name": name, "uts": uts})

                attr = loved.get("@attr", {})
                try:
                    total_pages = int(attr.get("totalPages", 1))
                except (ValueError, TypeError):
                    total_pages = 1
                if page >= total_pages:
                    break
                page += 1
    except httpx.RequestError as e:
        logger.warning("[Last.fm] Network error fetching loved tracks: %s", e)
        return LASTFM_ERROR

    return results


# ── Authenticated session (write) ────────────────────────────────


async def get_session_from_token(token: str) -> dict:
    """Exchange a one-time auth token for a session key. Returns {key, name}.

    Raises LastfmAuthError on any failure.
    """
    if not token:
        raise LastfmAuthError("Missing token.")
    api_key = get_lastfm_api_key()
    if not api_key:
        raise LastfmAuthError("LASTFM_API_KEY is not set.")

    params = {"method": "auth.getSession", "api_key": api_key, "token": token}
    params["api_sig"] = _sign(params)
    params["format"] = "json"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(LASTFM_API_URL, params=params)
    except httpx.RequestError as e:
        raise LastfmAuthError(f"Network error: {e}")

    try:
        data = r.json()
    except ValueError:
        raise LastfmAuthError(f"Invalid response: {r.text[:200]}")

    if r.status_code != 200 or "error" in data:
        msg = data.get("message", r.text[:200]) if isinstance(data, dict) else r.text[:200]
        raise LastfmAuthError(f"Last.fm rejected token: {msg}")

    sess = (data or {}).get("session") or {}
    key = sess.get("key")
    name = sess.get("name", "")
    if not key:
        raise LastfmAuthError(f"No session key in response: {data}")
    return {"key": key, "name": name}


async def track_love(artist: str, track: str, session_key: str) -> tuple[bool, str]:
    """Mark a track as Loved on Last.fm. Returns (ok, error_message).

    Last.fm's track.love accepts arbitrary strings — the call succeeds even
    when the (artist, track) pair isn't in their catalog. Treat that as
    success; the love still attaches to the user's profile.
    """
    if not artist or not track:
        return False, "Missing artist or track."
    if not session_key:
        return False, "Not authorized with Last.fm."
    api_key = get_lastfm_api_key()
    if not api_key:
        return False, "LASTFM_API_KEY is not set."

    params = {
        "method": "track.love",
        "artist": artist,
        "track": track,
        "api_key": api_key,
        "sk": session_key,
    }
    try:
        params["api_sig"] = _sign(params)
    except LastfmAuthError as e:
        return False, str(e)
    params["format"] = "json"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(LASTFM_API_URL, data=params)
    except httpx.RequestError as e:
        return False, f"Network error: {e}"

    if r.status_code != 200:
        try:
            err = r.json()
            return False, err.get("message", f"HTTP {r.status_code}")
        except ValueError:
            return False, f"HTTP {r.status_code}: {r.text[:200]}"

    try:
        data = r.json()
    except ValueError:
        return True, ""

    if isinstance(data, dict) and data.get("error"):
        return False, data.get("message", "Unknown Last.fm error")
    return True, ""


async def track_unlove(artist: str, track: str, session_key: str) -> tuple[bool, str]:
    """Remove a track from Loved on Last.fm. Returns (ok, error_message).

    Like track.love, this is idempotent on Last.fm's side: unloving a track
    that wasn't loved still returns success.
    """
    if not artist or not track:
        return False, "Missing artist or track."
    if not session_key:
        return False, "Not authorized with Last.fm."
    api_key = get_lastfm_api_key()
    if not api_key:
        return False, "LASTFM_API_KEY is not set."

    params = {
        "method": "track.unlove",
        "artist": artist,
        "track": track,
        "api_key": api_key,
        "sk": session_key,
    }
    try:
        params["api_sig"] = _sign(params)
    except LastfmAuthError as e:
        return False, str(e)
    params["format"] = "json"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(LASTFM_API_URL, data=params)
    except httpx.RequestError as e:
        return False, f"Network error: {e}"

    if r.status_code != 200:
        try:
            err = r.json()
            return False, err.get("message", f"HTTP {r.status_code}")
        except ValueError:
            return False, f"HTTP {r.status_code}: {r.text[:200]}"

    try:
        data = r.json()
    except ValueError:
        return True, ""

    if isinstance(data, dict) and data.get("error"):
        return False, data.get("message", "Unknown Last.fm error")
    return True, ""
