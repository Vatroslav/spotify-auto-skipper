"""
Background polling loop — async port of desktop app.py main_loop().
Runs as an asyncio task within FastAPI's lifespan.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from app.config import load_settings
from app.database import (
    add_log, add_track_event, get_oauth_tokens,
    is_artist_never_skipped, purge_old_logs,
)
from app.spotify_api import CredentialError
from app.lastfm_api import get_last_play_date, LASTFM_ERROR
from app.state import app_state


async def _log(message: str, level: str = "info"):
    """Write to DB log and print to stdout for Docker logs."""
    print(f"[{level.upper()}] {message}")
    await add_log(message, level)


async def polling_loop():
    """
    Continuously check what's playing, ask Last.fm if it was scrobbled recently,
    and skip if within the configured window.
    """
    recent_skip_days: list[int] = []

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
        await _log("Spotify token acquired. Worker started.")
    except CredentialError as e:
        await _log(f"Credential error: {e}", "error")
        app_state.worker_running = False
        return

    settings = await load_settings()
    await _log(f"Configuration: skip_window={settings['skip_window_days']}d, "
               f"poll_interval={settings['poll_interval_seconds']}s, "
               f"liked_songs={'on' if settings['always_play_liked_songs'] else 'off'}, "
               f"restart_pattern={'on' if settings['enable_restart_pattern'] else 'off'}")

    # Purge old data on startup, then every 24 hours
    await purge_old_logs(settings["log_retention_days"])
    last_purge = datetime.now(timezone.utc)

    while True:
        try:
            # Reload settings each cycle so changes take effect
            settings = await load_settings()
            poll_interval = settings["poll_interval_seconds"]

            # Periodic purge (every 24h)
            if (datetime.now(timezone.utc) - last_purge).total_seconds() >= 86400:
                await purge_old_logs(settings["log_retention_days"])
                last_purge = datetime.now(timezone.utc)

            # Update poll timestamp every cycle (for countdown timer)
            app_state.last_checked_timestamp = datetime.now(timezone.utc)

            # Manual pause
            if app_state.skipping_paused:
                await _log("Skipping is paused.")
                app_state.current_track = None
                await app_state.interruptible_sleep(poll_interval)
                continue

            track = await client.get_current_track()

            # Nothing playing
            if not track or not track.get("artist") or not track.get("id"):
                await _log("Nothing is playing right now.")
                app_state.current_track = None
                await app_state.interruptible_sleep(poll_interval)
                continue

            # Update cached current track for the dashboard
            app_state.current_track = track

            # Same song as last time
            if track["id"] == app_state.last_checked_track_id:
                await app_state.interruptible_sleep(poll_interval)
                continue

            # New song — remember it
            app_state.last_checked_track_id = track["id"]
            app_state.last_check_message = "Checking..."

            await _log(f"Currently playing: {track['artist']} \u2013 {track['name']}")

            # Get latest scrobble date from Last.fm
            last_played = await get_last_play_date(track["artist"], track["name"])

            if last_played is LASTFM_ERROR:
                await _log("Last.fm unavailable — skipping check for this song.", "warning")
                app_state.last_check_message = "Last.fm error"
                await app_state.interruptible_sleep(poll_interval)
                continue

            if last_played:
                days_since = (datetime.now(timezone.utc) - last_played).days
                await _log(f"Last scrobble: {last_played.strftime('%Y-%m-%d')} - {days_since} days ago")
                app_state.last_check_message = f"Last heard {days_since} day{'s' if days_since != 1 else ''} ago"

                cutoff = datetime.now(timezone.utc) - timedelta(days=settings["skip_window_days"])

                if last_played > cutoff:
                    # Check never-skip list
                    if settings["enable_never_skip_artists"] and await is_artist_never_skipped(track.get("artist_ids", [])):
                        await _log("Artist is in never-skip list \u2014 not skipping")
                        await add_track_event(
                            track["id"], track["name"], track["artist"],
                            "never_skip", days_since, track.get("context_uri"),
                        )
                    # Check liked songs
                    elif settings["always_play_liked_songs"] and await client.is_track_liked(track["id"]):
                        await _log("Track is in Liked Songs \u2014 not skipping")
                        await add_track_event(
                            track["id"], track["name"], track["artist"],
                            "liked", days_since, track.get("context_uri"),
                        )
                    else:
                        await _log(f"Already listened to {days_since} days ago \u2014 skipping")
                        was_paused = await client.is_spotify_paused()
                        await client.skip_current_track()
                        if was_paused:
                            await asyncio.sleep(1)
                            await client.pause_spotify_playback()

                        await add_track_event(
                            track["id"], track["name"], track["artist"],
                            "skipped", days_since, track.get("context_uri"),
                        )

                        # Track skip patterns for restart detection
                        if settings["enable_restart_pattern"]:
                            recent_skip_days.append(days_since)
                            threshold = settings["restart_pattern_song_count"]
                            if len(recent_skip_days) > threshold:
                                recent_skip_days.pop(0)

                            if (
                                len(recent_skip_days) == threshold
                                and max(recent_skip_days) - min(recent_skip_days) <= settings["restart_pattern_day_diff"]
                            ):
                                await _log(f"Detected repeating pattern ({threshold} skips) \u2014 restarting playlist...", "warning")
                                await client.restart_playlist(settings["dummy_playlist_id"])
                                recent_skip_days.clear()

                        await asyncio.sleep(3)
                        await _log("Checking the next song right away...")
                        continue
                else:
                    await _log("Last scrobble is older than the window \u2014 not skipping.")
                    await add_track_event(
                        track["id"], track["name"], track["artist"],
                        "played", days_since, track.get("context_uri"),
                    )
            else:
                await _log("No scrobble for this song \u2014 not skipping.")
                app_state.last_check_message = "Never heard before"
                await add_track_event(
                    track["id"], track["name"], track["artist"],
                    "no_scrobble", None, track.get("context_uri"),
                )

        except CredentialError as e:
            await _log(f"Credential error: {e}", "error")
            app_state.worker_running = False
            return
        except asyncio.CancelledError:
            await _log("Worker shutting down.")
            break
        except Exception as e:
            await _log(f"Unexpected error: {e}", "error")

        await app_state.interruptible_sleep(poll_interval)
