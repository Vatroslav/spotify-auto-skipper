"""
Playback API routes — current track, check now, pause/resume.
"""

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.config import load_settings
from app.database import add_log, add_track_alias, get_lastfm_session, get_track_alias, is_reauth_required
from app.lastfm_api import get_nowplaying, track_love, track_unlove
from app.loved_sync import _normalize, _similarity
from app.routers.deps import require_auth_or_device_token
from app.state import app_state

# Thresholds for auto-alias creation in toggle_like (see resolve_lastfm_name).
_AUTO_ALIAS_ARTIST_SIM = 1.0  # artist must match exactly (after normalize)
_AUTO_ALIAS_NAME_SIM = 0.8  # track name similarity floor

# Device tokens are accepted here only: these are the manual commands the
# Android Auto controller sends. Every other router stays session-only.
router = APIRouter(
    prefix="/api/playback",
    tags=["playback"],
    dependencies=[Depends(require_auth_or_device_token)],
)


async def _get_liked_cached(track_id: str) -> bool | None:
    """Liked status for track_id, cached across dashboard polls.

    The cache (app_state.liked_status_cache) holds only the current track, so a
    different track_id is a miss and triggers exactly one Spotify call. Returns
    None if the Spotify client is unavailable or the lookup fails — matching the
    prior get_playback behavior. On a Spotify-side like/unlike from another client
    the cached value stays until the song changes; toggle_like refreshes it here.
    """
    cache = app_state.liked_status_cache
    if track_id in cache:
        return cache[track_id]
    client = app_state.spotify_client
    if not client:
        return None
    try:
        is_liked = await client.is_track_liked(track_id)
    except Exception:
        return None
    # Single-entry cache: replace so previous track ids don't accumulate.
    app_state.liked_status_cache = {track_id: is_liked}
    return is_liked


@router.get("")
async def get_playback(request: Request):
    """Return current track info and worker status."""
    track = app_state.current_track
    settings = await load_settings()

    is_liked: bool | None = None
    if track and track.get("id"):
        is_liked = await _get_liked_cached(track["id"])

    return {
        "track": track,
        "skipping_paused": app_state.skipping_paused,
        "worker_running": app_state.worker_running,
        "reauth_required": await is_reauth_required(),
        "last_checked": app_state.last_checked_timestamp.isoformat() if app_state.last_checked_timestamp else None,
        "last_check_message": app_state.last_check_message,
        "poll_interval": settings["idle_poll_interval_seconds"]
        if app_state.idle_mode
        else settings["poll_interval_seconds"],
        "idle_mode": app_state.idle_mode,
        "skip_exempt_track_id": app_state.skip_exempt_track_id,
        "is_liked": is_liked,
    }


@router.post("/check-now")
async def check_now(request: Request):
    """Trigger an immediate poll cycle."""
    app_state.check_now_event.set()
    return {"ok": True}


@router.post("/skip-one-pause")
async def skip_one_pause(request: Request):
    """Exempt the currently playing song from being skipped (one-time).

    Fetches the current track directly from Spotify to ensure freshness.
    """
    client = app_state.spotify_client
    if not client:
        return JSONResponse({"ok": False, "error": "Spotify client not ready"}, status_code=503)
    track = await client.get_current_track()
    if not track or not track.get("id"):
        return JSONResponse({"ok": False, "error": "Nothing is playing"}, status_code=400)
    app_state.skip_exempt_track_id = track["id"]
    return {"ok": True, "track_name": track["name"], "artist": track["artist"]}


@router.post("/toggle-pause")
async def toggle_pause(request: Request):
    """Toggle pause/resume skipping."""
    app_state.skipping_paused = not app_state.skipping_paused
    return {"skipping_paused": app_state.skipping_paused}


@router.post("/remove-from-playlist")
async def remove_from_playlist(request: Request):
    """Remove the currently playing track from its playlist (back up to trash playlist if configured), then skip.

    Reproduces the AHK Ctrl+Media_Next workflow.
    """
    client = app_state.spotify_client
    if not client:
        return JSONResponse({"ok": False, "error": "Spotify client not ready"}, status_code=503)

    track = await client.get_current_track()
    if not track or not track.get("id"):
        return JSONResponse({"ok": False, "error": "Nothing is playing"}, status_code=400)

    context_uri = track.get("context_uri") or ""
    if not context_uri.startswith("spotify:playlist:"):
        return JSONResponse(
            {"ok": False, "error": "Currently playing track is not from a playlist"},
            status_code=400,
        )

    playlist_id = context_uri.split(":")[-1]
    track_uri = f"spotify:track:{track['id']}"
    track_label = f'"{track["name"]}" by {track["artist"]}'

    settings = await load_settings()
    trash_id = (settings.get("trash_playlist_id") or "").strip()

    # Back up to trash playlist if configured
    if trash_id:
        ok = await client.add_tracks_to_playlist(trash_id, [track_uri])
        if not ok:
            await add_log(
                f"Manual remove: failed to back up {track_label} to trash playlist {trash_id} — aborting",
                "warning",
            )
            return JSONResponse(
                {"ok": False, "error": "Failed to add to trash playlist (check trash_playlist_id)"},
                status_code=502,
            )

    # Remove from current playlist
    ok, err = await client.remove_tracks_from_playlist(playlist_id, [track_uri])
    if not ok:
        await add_log(
            f"Manual remove failed: {track_label} from playlist {playlist_id}: {err}",
            "warning",
        )
        return JSONResponse(
            {"ok": False, "error": err or "Failed to remove from playlist"},
            status_code=502,
        )

    # Skip to next, then trigger an immediate check on the new track.
    # Wait 1s so Spotify propagates the new track before the worker polls —
    # otherwise /currently-playing still returns the removed track and the
    # worker treats it as "same song" and sleeps a full poll interval.
    await client.skip_current_track()
    await asyncio.sleep(1)
    app_state.check_now_event.set()

    backup_suffix = f", backed up to {trash_id}" if trash_id else ""
    await add_log(
        f"Manually removed {track_label} from playlist {playlist_id}{backup_suffix}",
        "info",
    )

    return {
        "ok": True,
        "track_name": track["name"],
        "artist": track["artist"],
        "backed_up": bool(trash_id),
    }


async def _resolve_lastfm_name(track_id: str, artist: str, spotify_name: str) -> tuple[str, bool]:
    """Decide which track name to send to Last.fm love/unlove for this track.

    Resolution order:
      1. Existing alias in track_aliases → use it.
      2. Last.fm nowplaying for this user, when artist matches exactly (1.0
         after normalize) and the track name is similar enough (>= 0.8 after
         normalize) — if the Last.fm name differs from Spotify's, persist a
         new alias with user_confirmed=False so the user can review it later.
      3. Fallback: send the Spotify name verbatim, no alias touched.

    Returns (lastfm_name, auto_alias_created).
    """
    existing = await get_track_alias(track_id, artist, spotify_name)
    if existing:
        return existing, False

    np = await get_nowplaying()
    if not np:
        return spotify_name, False

    sp_artist_n = _normalize(artist)
    np_artist_n = _normalize(np["artist"])
    if not sp_artist_n or sp_artist_n != np_artist_n:
        return spotify_name, False  # artist mismatch — Last.fm probably stale

    sp_name_n = _normalize(spotify_name)
    np_name_n = _normalize(np["name"])
    if _similarity(sp_name_n, np_name_n) < _AUTO_ALIAS_NAME_SIM:
        return spotify_name, False  # name too different — different version

    if np["name"].strip().lower() == spotify_name.strip().lower():
        return spotify_name, False  # names match — no alias needed

    # Auto-alias: artist exact, name close-but-different
    await add_track_alias(track_id, artist, spotify_name, np["name"], user_confirmed=False)
    return np["name"], True


@router.post("/toggle-like")
async def toggle_like(request: Request):
    """Toggle current track's Liked status on Spotify and Loved status on Last.fm.

    If the track is currently Liked: remove from Spotify Liked Songs and unlove on Last.fm.
    If not Liked: add to both. Last.fm sync is best-effort — if the user hasn't authorized
    Last.fm, the Spotify side still succeeds.

    Last.fm name resolution: existing alias → Last.fm nowplaying inference (auto-aliased
    when artist matches and name is close-but-different) → Spotify name as-is.
    """
    client = app_state.spotify_client
    if not client:
        return JSONResponse({"ok": False, "error": "Spotify client not ready"}, status_code=503)

    track = await client.get_current_track()
    if not track or not track.get("id"):
        return JSONResponse({"ok": False, "error": "Nothing is playing"}, status_code=400)

    track_id = track["id"]
    track_label = f'"{track["name"]}" by {track["artist"]}'

    currently_liked = await client.is_track_liked(track_id)

    if currently_liked:
        ok, err = await client.remove_track_from_liked(track_id)
        if not ok:
            await add_log(f"Manual unlike failed: {track_label}: {err}", "warning")
            return JSONResponse(
                {"ok": False, "error": err or "Spotify unlike failed"}, status_code=502
            )
        new_state = False
        action_word = "Unliked"
    else:
        ok, err = await client.save_track_to_liked(track_id)
        if not ok:
            await add_log(f"Manual like failed: {track_label}: {err}", "warning")
            return JSONResponse(
                {"ok": False, "error": err or "Spotify like failed"}, status_code=502
            )
        new_state = True
        action_word = "Liked"

    # Refresh the dashboard cache so the next poll reflects the toggle immediately
    # (otherwise the button would flip back to the stale cached state).
    app_state.liked_status_cache = {track_id: new_state}

    lastfm_synced: bool | None = None
    lastfm_error: str | None = None
    lastfm_name_used: str | None = None
    auto_alias_created = False
    session = await get_lastfm_session()
    if session and session.get("session_key"):
        lastfm_name_used, auto_alias_created = await _resolve_lastfm_name(
            track_id, track["artist"], track["name"]
        )
        if auto_alias_created:
            await add_log(
                f"Auto-aliased '{track['name']}' → '{lastfm_name_used}' from Last.fm nowplaying",
                "info",
            )
        if new_state:
            lf_ok, lf_err = await track_love(
                track["artist"], lastfm_name_used, session["session_key"]
            )
            lf_verb = "Loved"
        else:
            lf_ok, lf_err = await track_unlove(
                track["artist"], lastfm_name_used, session["session_key"]
            )
            lf_verb = "Unloved"
        lastfm_synced = lf_ok
        if not lf_ok:
            lastfm_error = lf_err
            await add_log(
                f"{action_word} {track_label} on Spotify, but Last.fm sync failed: {lf_err}",
                "warning",
            )
        else:
            sent_as = (
                f" (sent as '{lastfm_name_used}')" if lastfm_name_used != track["name"] else ""
            )
            await add_log(
                f"{action_word} {track_label} on Spotify, {lf_verb} on Last.fm{sent_as}", "info"
            )
    else:
        await add_log(f"{action_word} {track_label} on Spotify (Last.fm not authorized)", "info")

    return {
        "ok": True,
        "is_liked": new_state,
        "track_name": track["name"],
        "artist": track["artist"],
        "lastfm_synced": lastfm_synced,
        "lastfm_error": lastfm_error,
        "lastfm_name_used": lastfm_name_used,
        "auto_alias_created": auto_alias_created,
    }
