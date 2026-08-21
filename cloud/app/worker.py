"""
Background polling loop — async port of desktop app.py main_loop().
Runs as an asyncio task within FastAPI's lifespan.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from app.config import load_settings
from app.database import (
    add_log,
    add_track_event,
    get_last_track_event_id,
    get_oauth_tokens,
    is_artist_never_skipped,
    purge_old_logs,
    recompute_overall_metrics,
    set_reauth_required,
)
from app.lastfm_api import LASTFM_ERROR, get_last_play_date
from app.observability import report_exception
from app.spotify_api import CredentialError, ReauthRequiredError
from app.state import app_state


async def _log(message: str, level: str = "info"):
    """Write to DB log and print to stdout for Docker logs."""
    print(f"[{level.upper()}] {message}")
    await add_log(message, level)


# Adaptive skip window: after N consecutive skips, temporarily narrow the window
# so more songs pass through. Each level cuts the window by 33% of the base.
ADAPTIVE_STEP_SIZE = 5
ADAPTIVE_MAX_LEVEL = 2
ADAPTIVE_REDUCTION_PER_LEVEL = 0.33


def _adaptive_level(consecutive_skips: int) -> int:
    return min(consecutive_skips // ADAPTIVE_STEP_SIZE, ADAPTIVE_MAX_LEVEL)


def _effective_window(base_days: int, level: int) -> int:
    return max(1, int(round(base_days * (1 - ADAPTIVE_REDUCTION_PER_LEVEL * level))))


async def polling_loop():
    """
    Continuously check what's playing, ask Last.fm if it was scrobbled recently,
    and skip if within the configured window.
    """
    recent_skip_days: list[int] = []
    consecutive_idle: int = 0
    consecutive_skips: int = 0
    adaptive_level: int = 0

    async def _update_skip_streak(was_skip: bool):
        nonlocal consecutive_skips, adaptive_level
        new_count = consecutive_skips + 1 if was_skip else 0
        if not settings.get("enable_adaptive_skip_window"):
            consecutive_skips = new_count
            adaptive_level = 0
            return
        new_level = _adaptive_level(new_count)
        if new_level != adaptive_level:
            base = settings["skip_window_days"]
            if new_level > 0:
                await _log(
                    f"Adaptive skip window: {new_count} consecutive skips — "
                    f"narrowing window to {_effective_window(base, new_level)}d (base {base}d)",
                    "warning",
                )
            else:
                await _log(
                    f"Adaptive skip window: streak broken — restoring window to {base}d"
                )
        consecutive_skips = new_count
        adaptive_level = new_level

    # Wait for OAuth tokens to be available
    while True:
        tokens = await get_oauth_tokens()
        if tokens and tokens.get("refresh_token"):
            break
        await _log("Waiting for Spotify authorization... Visit /auth/login to connect.", "warning")
        await asyncio.sleep(10)

    client = app_state.spotify_client

    try:
        await client.get_token()
        # A successful token acquisition means any prior re-auth requirement is
        # resolved — self-heal the persisted flag in case it was left stale.
        await set_reauth_required(False)
        await _log("Spotify token acquired. Worker started.")
    except ReauthRequiredError as e:
        await _log(f"Spotify re-authorization required: {e} — visit /auth/login to reconnect.", "error")
        app_state.worker_running = False
        return
    except CredentialError as e:
        await _log(f"Credential error: {e}", "error")
        app_state.worker_running = False
        return

    settings = await load_settings()
    await _log(
        f"Configuration: skip_window={settings['skip_window_days']}d, "
        f"poll_interval={settings['poll_interval_seconds']}s, "
        f"idle_threshold={settings['idle_threshold']}, "
        f"idle_poll_interval={settings['idle_poll_interval_seconds']}s, "
        f"liked_songs={'on' if settings['always_play_liked_songs'] else 'off'}, "
        f"restart_pattern={'on' if settings['enable_restart_pattern'] else 'off'}, "
        f"adaptive_window={'on' if settings['enable_adaptive_skip_window'] else 'off'}"
    )

    # Purge old data on startup, then every 24 hours
    await purge_old_logs(settings["log_retention_days"])
    await recompute_overall_metrics()
    app_state.last_checked_track_id = await get_last_track_event_id()
    last_purge = datetime.now(timezone.utc)

    # Seed poll_interval before the loop so the trailing sleep (and the generic
    # exception handler's sleep) always has a value. Otherwise a load_settings()
    # failure on the very first iteration would leave poll_interval unassigned,
    # and the sleep on the last line of the loop would raise NameError — killing
    # the worker instead of retrying.
    poll_interval = settings["poll_interval_seconds"]

    while True:
        try:
            # Reload settings each cycle so changes take effect
            settings = await load_settings()
            poll_interval = settings["poll_interval_seconds"]

            # Periodic purge + metrics recompute (every 24h)
            if (datetime.now(timezone.utc) - last_purge).total_seconds() >= 86400:
                await purge_old_logs(settings["log_retention_days"])
                await recompute_overall_metrics()
                last_purge = datetime.now(timezone.utc)

            # Update poll timestamp every cycle (for countdown timer)
            app_state.last_checked_timestamp = datetime.now(timezone.utc)

            # Adaptive polling: determine sleep interval
            idle_threshold = settings["idle_threshold"]
            idle_poll_interval = settings["idle_poll_interval_seconds"]

            track = await client.get_current_track()

            # Nothing playing
            if not track or not track.get("artist") or not track.get("id"):
                consecutive_idle += 1
                if not app_state.idle_mode and consecutive_idle >= idle_threshold:
                    app_state.idle_mode = True
                    await _log(
                        f"Nothing playing for {consecutive_idle} checks "
                        f"— switching to slow polling ({idle_poll_interval}s)."
                    )
                else:
                    await _log("Nothing is playing right now.")
                app_state.current_track = None
                app_state.current_track_captured_at = None
                sleep_interval = idle_poll_interval if app_state.idle_mode else poll_interval
                await app_state.interruptible_sleep(sleep_interval)
                continue

            # Update cached current track for the dashboard
            app_state.current_track = track
            app_state.current_track_captured_at = datetime.now(timezone.utc)

            # Playback detected — exit idle mode
            if app_state.idle_mode:
                await _log("Playback detected — resuming normal polling.")
                app_state.idle_mode = False
            consecutive_idle = 0

            # Manual pause. Deliberately placed after the fetch so the dashboard
            # still shows what's playing; only the Last.fm lookup and the skip
            # decision are suspended. last_checked_track_id is left untouched, so
            # on resume the current song is treated as unchecked and gets its
            # normal skip decision.
            if app_state.skipping_paused:
                await _log("Skipping is paused.")
                # A song that started while paused was never checked, so the
                # previous song's verdict must not stay on the dashboard next
                # to it. An already-checked song keeps its real verdict.
                if track["id"] != app_state.last_checked_track_id:
                    app_state.last_check_message = "Not checked — skipping paused"
                await app_state.interruptible_sleep(poll_interval)
                continue

            # Same song as last time
            if track["id"] == app_state.last_checked_track_id:
                await app_state.interruptible_sleep(poll_interval)
                continue

            # New song — remember it
            app_state.last_checked_track_id = track["id"]
            app_state.last_check_message = "Checking..."

            await _log(f"Currently playing: {track['artist']} \u2013 {track['name']}")

            # Get latest scrobble date from Last.fm (retry up to 3 times)
            last_played = None
            for attempt in range(3):
                last_played = await get_last_play_date(track["artist"], track["name"], track["id"])
                if last_played is not LASTFM_ERROR:
                    break
                if attempt < 2:
                    await _log(f"Last.fm unavailable — retrying ({attempt + 2}/3)...", "warning")
                    await asyncio.sleep(5)

            if last_played is LASTFM_ERROR:
                await _log("Last.fm unavailable after 3 attempts — skipping check for this song.", "warning")
                app_state.last_check_message = "Last.fm error"
                await app_state.interruptible_sleep(poll_interval)
                continue

            if last_played:
                days_since = (datetime.now(timezone.utc) - last_played).days
                await _log(f"Last scrobble: {last_played.strftime('%Y-%m-%d')} - {days_since} days ago")
                app_state.last_check_message = f"Last heard {days_since} day{'s' if days_since != 1 else ''} ago"

                effective_window_days = (
                    _effective_window(settings["skip_window_days"], adaptive_level)
                    if settings.get("enable_adaptive_skip_window")
                    else settings["skip_window_days"]
                )
                cutoff = datetime.now(timezone.utc) - timedelta(days=effective_window_days)

                if last_played > cutoff:
                    # Check one-time skip pause
                    if app_state.skip_exempt_track_id == track["id"]:
                        await _log("Skip paused for this song (one-time) — not skipping")
                        app_state.skip_exempt_track_id = None
                        await add_track_event(
                            track["id"],
                            track["name"],
                            track["artist"],
                            "skip_paused",
                            days_since,
                            track.get("context_uri"), album_name=track.get("album"),
                        )
                        await _update_skip_streak(False)
                    # Check never-skip list
                    elif settings["enable_never_skip_artists"] and await is_artist_never_skipped(
                        track.get("artist_ids", [])
                    ):
                        await _log("Artist is in never-skip list \u2014 not skipping")
                        await add_track_event(
                            track["id"],
                            track["name"],
                            track["artist"],
                            "never_skip",
                            days_since,
                            track.get("context_uri"), album_name=track.get("album"),
                        )
                        await _update_skip_streak(False)
                    # Check liked songs
                    elif settings["always_play_liked_songs"] and await client.is_track_liked(track["id"]):
                        await _log("Track is in Liked Songs \u2014 not skipping")
                        await add_track_event(
                            track["id"],
                            track["name"],
                            track["artist"],
                            "liked",
                            days_since,
                            track.get("context_uri"), album_name=track.get("album"),
                        )
                        await _update_skip_streak(False)
                    else:
                        # Re-check pause flag right before skipping (user may have
                        # pressed Pause while we were querying Last.fm)
                        if app_state.skipping_paused:
                            await _log("Skipping was paused while checking \u2014 not skipping")
                            await add_track_event(
                                track["id"],
                                track["name"],
                                track["artist"],
                                "skip_paused",
                                days_since,
                                track.get("context_uri"), album_name=track.get("album"),
                            )
                            await _update_skip_streak(False)
                            await app_state.interruptible_sleep(poll_interval)
                            continue

                        await _log(f"Already listened to {days_since} days ago \u2014 skipping")
                        was_paused = await client.is_spotify_paused()
                        await client.skip_current_track()
                        if was_paused:
                            await asyncio.sleep(1)
                            await client.pause_spotify_playback()

                        await add_track_event(
                            track["id"],
                            track["name"],
                            track["artist"],
                            "skipped",
                            days_since,
                            track.get("context_uri"), album_name=track.get("album"),
                        )
                        await _update_skip_streak(True)

                        # Track skip patterns for restart detection
                        if settings["enable_restart_pattern"]:
                            recent_skip_days.append(days_since)
                            threshold = settings["restart_pattern_song_count"]
                            if len(recent_skip_days) > threshold:
                                recent_skip_days.pop(0)

                            if (
                                len(recent_skip_days) == threshold
                                and max(recent_skip_days) - min(recent_skip_days)
                                <= settings["restart_pattern_day_diff"]
                            ):
                                await _log(
                                    f"Detected repeating pattern ({threshold} skips) \u2014 restarting playlist...",
                                    "warning",
                                )
                                if not await client.restart_playlist(settings["dummy_playlist_id"]):
                                    await _log(
                                        "Playlist restart failed — check the dummy playlist ID in settings.",
                                        "warning",
                                    )
                                recent_skip_days.clear()

                        await asyncio.sleep(1)
                        await _log("Checking the next song right away...")
                        continue
                else:
                    await _log("Last scrobble is older than the window \u2014 not skipping.")
                    await add_track_event(
                        track["id"],
                        track["name"],
                        track["artist"],
                        "played",
                        days_since,
                        track.get("context_uri"), album_name=track.get("album"),
                    )
                    await _update_skip_streak(False)
            else:
                await _log("No scrobble for this song \u2014 not skipping.")
                app_state.last_check_message = "Never heard before"
                await add_track_event(
                    track["id"],
                    track["name"],
                    track["artist"],
                    "no_scrobble",
                    None,
                    track.get("context_uri"), album_name=track.get("album"),
                )
                await _update_skip_streak(False)

        except ReauthRequiredError as e:
            # Refresh token died (e.g. six-month expiry). The dead token and the
            # persisted re-auth flag are already handled in refresh_access_token;
            # surface it and stop so the dashboard can prompt a reconnect.
            await _log(f"Spotify re-authorization required: {e} — visit /auth/login to reconnect.", "error")
            app_state.worker_running = False
            return
        except CredentialError as e:
            await _log(f"Credential error: {e}", "error")
            app_state.worker_running = False
            return
        except asyncio.CancelledError:
            await _log("Worker shutting down.")
            break
        except Exception as e:
            await _log(f"Unexpected error: {e}", "error")
            report_exception(e, component="worker")

        await app_state.interruptible_sleep(poll_interval)


# ── Worker supervision ──────────────────────────────────────────────
#
# The polling loop catches its own runtime errors, but a few paths can still
# take the whole task down: an exception in the pre-loop setup (token/DB/settings),
# or anything that escapes the `while` body (the historical NameError, v3.16.1).
# `restart: unless-stopped` only reacts to the *process* exiting, not to a dead
# worker task, so a crashed worker would otherwise leave the app up-but-idle
# (health 503) until someone noticed. The supervisor closes that gap in-process.
#
# It restarts the worker ONLY on a crash. A clean return — re-auth / credential
# needed — is left alone on purpose: the token in the DB is dead, so restarting
# would just re-hit the same path and loop; that state waits for the user to
# reconnect at /auth/login (which calls restart_worker_if_dead itself).
#
# A fully wedged process (blocked event loop, dead uvicorn) is out of scope here
# — the supervisor runs on the same loop, so it can't fix that. That tail is left
# as signal-only via the Docker HEALTHCHECK; see CLAUDE.md (Health Monitoring).

WORKER_CHECK_INTERVAL = 30  # seconds between health checks of the worker task
WORKER_RESTART_BACKOFF_MAX = 300  # cap on the crash backoff so logs don't spam


async def worker_supervisor():
    """Watch the polling loop and restart it if it died from an unexpected crash."""
    consecutive_crashes = 0
    while True:
        delay = (
            min(WORKER_CHECK_INTERVAL * (2 ** (consecutive_crashes - 1)), WORKER_RESTART_BACKOFF_MAX)
            if consecutive_crashes
            else WORKER_CHECK_INTERVAL
        )
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            break

        task = app_state.worker_task
        if task is None or not task.done():
            consecutive_crashes = 0
            continue
        if task.cancelled():
            # App is shutting down (worker was cancelled) — stop supervising.
            break

        exc = task.exception()  # also marks it retrieved, silencing asyncio's warning
        if exc is None:
            # Clean stop: re-auth / credential needed. Not a crash — wait for the
            # user to reconnect rather than loop on a dead token.
            consecutive_crashes = 0
            continue

        consecutive_crashes += 1
        await _log(
            f"Worker crashed ({type(exc).__name__}: {exc}) — restarting "
            f"(attempt {consecutive_crashes}).",
            "error",
        )
        report_exception(exc, component="worker-supervisor")
        app_state.restart_worker_if_dead()
