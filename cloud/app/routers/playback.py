"""
Playback API routes — current track, check now, pause/resume.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.config import load_settings
from app.database import add_log, get_lastfm_session
from app.lastfm_api import track_love, track_unlove
from app.routers.deps import require_auth
from app.state import app_state

router = APIRouter(prefix="/api/playback", tags=["playback"], dependencies=[Depends(require_auth)])


@router.get("")
async def get_playback(request: Request):
    """Return current track info and worker status."""
    track = app_state.current_track
    settings = await load_settings()

    is_liked: bool | None = None
    if track and track.get("id"):
        client = app_state.spotify_client
        if client:
            try:
                is_liked = await client.is_track_liked(track["id"])
            except Exception:
                is_liked = None

    return {
        "track": track,
        "skipping_paused": app_state.skipping_paused,
        "worker_running": app_state.worker_running,
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

    # Skip to next, then trigger an immediate check on the new track
    await client.skip_current_track()
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


@router.post("/toggle-like")
async def toggle_like(request: Request):
    """Toggle current track's Liked status on Spotify and Loved status on Last.fm.

    If the track is currently Liked: remove from Spotify Liked Songs and unlove on Last.fm.
    If not Liked: add to both. Last.fm sync is best-effort — if the user hasn't authorized
    Last.fm, the Spotify side still succeeds.
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

    lastfm_synced: bool | None = None
    lastfm_error: str | None = None
    session = await get_lastfm_session()
    if session and session.get("session_key"):
        if new_state:
            lf_ok, lf_err = await track_love(track["artist"], track["name"], session["session_key"])
        else:
            lf_ok, lf_err = await track_unlove(track["artist"], track["name"], session["session_key"])
        lastfm_synced = lf_ok
        if not lf_ok:
            lastfm_error = lf_err
            await add_log(
                f"{action_word} {track_label} on Spotify, but Last.fm sync failed: {lf_err}",
                "warning",
            )
        else:
            await add_log(f"{action_word} {track_label} on Spotify and Last.fm", "info")
    else:
        await add_log(f"{action_word} {track_label} on Spotify (Last.fm not authorized)", "info")

    return {
        "ok": True,
        "is_liked": new_state,
        "track_name": track["name"],
        "artist": track["artist"],
        "lastfm_synced": lastfm_synced,
        "lastfm_error": lastfm_error,
    }
