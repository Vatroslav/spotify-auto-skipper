"""
Lyrics API — time-synced words for the Android Auto display.

Deliberately makes no Spotify call. The car polls this endpoint every few
seconds and a per-poll Spotify request is exactly the pattern that cost us 720
requests/hour once already (see the spotify-api conventions). Position is
instead extrapolated from the worker's last snapshot: progress advances at one
millisecond per millisecond, so a snapshot plus its age is as good as a fresh
read for as long as nobody seeks.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from app.database import get_cached_lyrics, save_lyrics
from app.lyrics_api import fetch_lyrics, parse_lrc
from app.routers.deps import require_auth_or_device_token
from app.state import app_state

logger = logging.getLogger(__name__)

# Device tokens are accepted here for the same reason as on the playback
# router: this is what the car controller reads. Read-only either way.
router = APIRouter(
    prefix="/api/lyrics",
    tags=["lyrics"],
    dependencies=[Depends(require_auth_or_device_token)],
)


def _extrapolated_position(track: dict, captured_at: datetime | None) -> int:
    """Where playback is now, from where it was when the worker last looked.

    A paused track stays put — without that check the display would scroll on
    through a pause. Clamped to the track length so a stale snapshot of a
    finished song reports the end rather than a position past it.
    """
    progress = int(track.get("progress_ms") or 0)
    duration = int(track.get("duration_ms") or 0)
    if not track.get("is_playing", True) or captured_at is None:
        return progress
    age_ms = int((datetime.now(timezone.utc) - captured_at).total_seconds() * 1000)
    position = progress + max(0, age_ms)
    return min(position, duration) if duration else position


async def _resolve_lyrics(track: dict) -> dict:
    """Cache-first lyrics for a track, fetching from LRCLIB on a miss.

    Returns the stored shape ({synced, plain, instrumental, found}) so callers
    treat a fresh fetch and a cache hit identically. A failed lookup is cached
    as a miss: a song LRCLIB does not have would otherwise be re-requested on
    every poll for the whole length of the song.
    """
    track_id = track["id"]
    cached = await get_cached_lyrics(track_id)
    if cached is not None:
        return cached

    result = await fetch_lyrics(
        artist=track.get("artist") or "",
        track=track.get("name") or "",
        album=track.get("album") or "",
        duration_ms=int(track.get("duration_ms") or 0),
    )

    if result is None:
        await save_lyrics(track_id, found=False)
        return {"synced": "", "plain": "", "instrumental": False, "found": False}

    await save_lyrics(
        track_id,
        synced=result.synced,
        plain=result.plain,
        instrumental=result.instrumental,
        found=True,
    )
    return {
        "synced": result.synced,
        "plain": result.plain,
        "instrumental": result.instrumental,
        "found": True,
    }


def _lines_and_state(lyrics: dict) -> tuple[list[dict], str]:
    """Turn a stored lyrics row into display lines plus a one-word state.

    States the car renders differently:
      synced      — timed lines, scrolls itself
      plain_only  — text but no timings, tap-to-advance only
      instrumental— LRCLIB knows the song and says there is nothing to show
      not_found   — LRCLIB has no entry
    """
    if not lyrics["found"]:
        return [], "not_found"
    if lyrics["instrumental"]:
        return [], "instrumental"

    parsed = parse_lrc(lyrics["synced"])
    if parsed:
        return parsed, "synced"

    plain = [line.strip() for line in (lyrics["plain"] or "").splitlines()]
    if any(plain):
        return [{"t": None, "text": line} for line in plain], "plain_only"
    return [], "not_found"


@router.get("")
async def get_lyrics(known_track_id: str | None = Query(default=None)):
    """Lyrics and playback position for whatever is playing right now.

    known_track_id is what the caller already holds. When it matches the
    playing track the lines are omitted from the response — the car polls this
    every few seconds for the position alone, and a full lyric sheet per poll
    is pure waste over a phone connection.

    snapshot_age_ms lets the caller judge the position it is given: the worker
    polls on its own schedule (up to the idle interval), so a large age means
    the position is an extrapolation over a long gap and a check-now would
    tighten it.
    """
    track = app_state.current_track
    captured_at = app_state.current_track_captured_at

    if not track or not track.get("id"):
        return {
            "state": "nothing_playing",
            "track": None,
            "lines": [],
            "lines_included": True,
            "position_ms": 0,
            "is_playing": False,
            "snapshot_age_ms": None,
        }

    lyrics = await _resolve_lyrics(track)
    lines, state = _lines_and_state(lyrics)
    include_lines = known_track_id != track["id"]

    age_ms = (
        int((datetime.now(timezone.utc) - captured_at).total_seconds() * 1000)
        if captured_at
        else None
    )

    return {
        "state": state,
        "track": {
            "id": track["id"],
            "name": track.get("name"),
            "artist": track.get("artist"),
            "duration_ms": int(track.get("duration_ms") or 0),
        },
        "lines": lines if include_lines else [],
        "lines_included": include_lines,
        "position_ms": _extrapolated_position(track, captured_at),
        "is_playing": bool(track.get("is_playing", True)),
        "snapshot_age_ms": age_ms,
    }
