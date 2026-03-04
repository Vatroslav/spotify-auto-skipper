import time
import sys
import os
import ctypes
import builtins
from datetime import datetime, timedelta, timezone

from spotify_auto_skipper import APP_VERSION
from spotify_auto_skipper import utils
from spotify_auto_skipper import config
from spotify_auto_skipper.config import load_config
from spotify_auto_skipper.spotify_api import (
    get_spotify_token, get_current_track, skip_current_track,
    is_spotify_paused, pause_spotify_playback, restart_playlist,
    is_skipping_enabled, is_track_liked, is_artist_never_skipped,
    get_artist_names_from_ids,
    get_playlist_track_ids, extract_playlist_id_from_uri,
)
from spotify_auto_skipper.lastfm_api import get_last_play_date
from spotify_auto_skipper.tray import create_tray_icon, open_settings_event


# Module-level refs set by _setup_logging()
_original_print = None
_log_file = None
_log_dir = None
_log_filename = None


# -----------------------------------------------------------------
# Mutex — prevent multiple instances
# -----------------------------------------------------------------

def _check_single_instance():
    """Use Windows mutex to ensure only one instance runs."""
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "SpotifyAutoSkipperMutex")
    last_error = ctypes.windll.kernel32.GetLastError()

    if last_error == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.user32.MessageBoxW(
            0,
            "Spotify Auto-Skipper is already running and running in the background.",
            "Already started",
            0x40,  # MB_ICONINFORMATION
        )
        sys.exit(0)

    # Keep a reference to prevent garbage collection
    return mutex


# -----------------------------------------------------------------
# Logging
# -----------------------------------------------------------------

def _setup_logging():
    """Redirect stdout/stderr to daily log file and install timestamp print."""
    global _original_print, _log_file, _log_dir, _log_filename

    _log_dir = utils.get_log_dir()

    _log_filename = datetime.now().strftime("%Y-%m-%d") + ".txt"
    log_path = os.path.join(_log_dir, _log_filename)

    _log_file = open(log_path, "a", encoding="utf-8")

    sys.stdout = _log_file
    sys.stderr = _log_file

    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    # Override builtins.print so ALL modules get timestamps
    _original_print = builtins.print

    def timestamped_print(*args, **kwargs):
        time_prefix = datetime.now().strftime("[%H:%M:%S]")
        text = " ".join(str(a) for a in args)
        if "\U0001f3b5" in text:
            _original_print("")  # blank line before song lines
        _original_print(time_prefix, text, **kwargs)
        sys.stdout.flush()

    builtins.print = timestamped_print


def _purge_old_logs():
    """Delete log files older than configured retention days."""
    try:
        cutoff_date = datetime.now() - timedelta(days=config.LOG_RETENTION_DAYS)
        deleted_files = []

        for filename in os.listdir(_log_dir):
            file_path = os.path.join(_log_dir, filename)

            if not os.path.isfile(file_path):
                continue
            if filename == _log_filename:
                continue

            if filename.endswith('.txt'):
                try:
                    date_str = filename[:-4]
                    file_date = datetime.strptime(date_str, "%Y-%m-%d")
                    if file_date < cutoff_date:
                        os.remove(file_path)
                        deleted_files.append(filename)
                except (ValueError, OSError):
                    pass

        return len(deleted_files), deleted_files

    except Exception as e:
        print(f"\u26a0\ufe0f Warning: Failed to purge old logs: {e}")
        return 0, []


def _print_startup_header():
    """Print the startup header and purge results."""
    deleted_count, deleted_files = _purge_old_logs()
    if deleted_count > 0:
        print(f"\U0001f5d1\ufe0f Purged {deleted_count} old log file(s) (older than {config.LOG_RETENTION_DAYS} days)")
        for filename in deleted_files:
            print(f"   - Deleted: {filename}")

    _original_print(f"\n{'='*60}")
    _original_print(f"\U0001f552 Starting the app ({APP_VERSION}): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    _original_print(f"{'='*60}\n")
    sys.stdout.flush()


# -----------------------------------------------------------------
# Artist name resolution
# -----------------------------------------------------------------

def _resolve_missing_artist_names():
    """
    If any never-skip artists have an ID but no name (from old config format),
    look them up via Spotify API and save the names back to config.
    """
    artists = config.NEVER_SKIP_ARTISTS
    if not artists:
        return

    needs_update = [a for a in artists if isinstance(a, dict) and a.get("id") and not a.get("name")]
    if not needs_update:
        return

    print(f"Resolving names for {len(needs_update)} never-skip artist(s)...")
    ids_to_resolve = [a["id"] for a in needs_update]
    resolved_names = get_artist_names_from_ids(ids_to_resolve)

    # Update the in-memory list
    for artist_dict, name in zip(needs_update, resolved_names):
        artist_dict["name"] = name

    # Persist to config so this only happens once
    cfg = config.Config()
    cfg.set("never_skip_artists", artists)
    cfg.save()

    # Reload module-level variables
    load_config()
    print("Artist names resolved and saved.")


# -----------------------------------------------------------------
# Main loop
# -----------------------------------------------------------------

def _show_recommendation_notification(track):
    """Show the desktop notification for a Smart Shuffle recommendation."""
    print(f"\u2728 Smart Shuffle recommendation: {track['artist']} \u2013 {track['name']}")
    try:
        from winotify import Notification, audio
        toast = Notification(
            app_id="Spotify Auto-Skipper",
            title="Smart Shuffle Recommendation",
            msg=f"{track['artist']} \u2013 {track['name']}",
            duration="long",
            icon=os.path.abspath(utils.resource_path("assets/app.ico")),
            launch="spotify:",
        )
        toast.set_audio(audio.Default, loop=False)
        toast.show()
    except Exception as e:
        print(f"\u26a0\ufe0f Failed to show notification: {e}")


def _check_recommendation(track):
    """
    Check if the currently playing track is a Smart Shuffle recommendation
    (i.e., not in the original playlist). If so, queue a pending notification
    that will be shown after 50% of the song has played.
    """
    if not config.ENABLE_RECOMMENDATION_NOTIFICATIONS:
        return

    context_uri = track.get("context_uri")
    playlist_id = extract_playlist_id_from_uri(context_uri)

    if not playlist_id:
        return  # not playing from a playlist

    # If playlist changed, fetch and cache the new track list
    if playlist_id != utils.cached_playlist_id:
        print(f"\U0001f4cb Playlist context changed ({playlist_id}), fetching track list...")
        track_ids = get_playlist_track_ids(playlist_id)
        if track_ids is None:
            print("\u26a0\ufe0f Could not fetch playlist tracks, skipping recommendation check")
            return
        utils.cached_playlist_id = playlist_id
        utils.cached_playlist_track_ids = track_ids
        print(f"\u2705 Cached {len(track_ids)} tracks from playlist")

    # Check if current track is NOT in the playlist (= Smart Shuffle recommendation)
    if track["id"] not in utils.cached_playlist_track_ids:
        # Re-fetch playlist to avoid false positives (e.g. user added song after cache)
        track_ids = get_playlist_track_ids(playlist_id)
        if track_ids is not None:
            utils.cached_playlist_track_ids = track_ids
            if track["id"] in track_ids:
                print(f"\u2705 {track['artist']} \u2013 {track['name']} was added to playlist since last cache \u2014 not a recommendation")
                return

        duration_ms = track.get("duration_ms", 0)
        print(f"\u23f3 Smart Shuffle recommendation detected: {track['artist']} \u2013 {track['name']} (notification after 50%)")
        utils.pending_recommendation_track = dict(track)
        utils.pending_recommendation_duration_ms = duration_ms


def _check_pending_recommendation(track):
    """
    Check if a pending Smart Shuffle recommendation has reached 50% playback.
    If so, show the notification and clear the pending state.
    Returns True if a recommendation is still pending (caller should use shorter sleep).
    """
    if utils.pending_recommendation_track is None:
        return False

    # Song changed — cancel pending notification
    if track["id"] != utils.pending_recommendation_track["id"]:
        print("\u274c Pending recommendation cancelled (song changed)")
        utils.pending_recommendation_track = None
        utils.pending_recommendation_duration_ms = 0
        return False

    duration_ms = utils.pending_recommendation_duration_ms
    progress_ms = track.get("progress_ms", 0)

    # Unknown duration — show immediately as fallback
    if duration_ms <= 0:
        _show_recommendation_notification(utils.pending_recommendation_track)
        utils.pending_recommendation_track = None
        utils.pending_recommendation_duration_ms = 0
        return False

    if progress_ms >= duration_ms / 2:
        _show_recommendation_notification(utils.pending_recommendation_track)
        utils.pending_recommendation_track = None
        utils.pending_recommendation_duration_ms = 0
        return False

    # Still pending
    pct = progress_ms / duration_ms * 100
    remaining_s = (duration_ms / 2 - progress_ms) / 1000
    print(f"\u23f3 Recommendation pending: {pct:.0f}% played, ~{remaining_s:.0f}s until 50%")
    return True


def main_loop():
    """
    Continuously check what's playing, ask Last.fm if it was scrobbled recently,
    and skip if within the configured window.
    """
    recent_skip_days = []

    get_spotify_token()

    # Resolve missing artist names (one-time migration from old ID-only format)
    _resolve_missing_artist_names()

    # Log configuration
    print("\U0001f680 Auto-skipper enabled. Here's the configuration:")
    print(f"   \u2022 Skipping songs that have been listened to in the last {config.SKIP_WINDOW_DAYS} days.")
    print(f"   \u2022 Retrieving the currently playing song every {config.POLL_INTERVAL_SECONDS} seconds.")

    if config.ALWAYS_PLAY_LIKED_SONGS:
        print("   \u2022 Will always play liked songs.")
    else:
        print("   \u2022 Will skip liked songs if they were played within the skip window.")

    if config.ENABLE_RESTART_PATTERN:
        print(f"   \u2022 Will restart the playlist if a repeated pattern is detected ({config.RESTART_PATTERN_SONG_COUNT} skips within \u00b1{config.RESTART_PATTERN_DAY_DIFF} days).")
    else:
        print("   \u2022 Won't restart the playlist if a repeated pattern is detected.")

    if config.ENABLE_RECOMMENDATION_NOTIFICATIONS:
        print("   \u2022 Will notify when Smart Shuffle recommendations play.")
    else:
        print("   \u2022 Smart Shuffle recommendation notifications are disabled.")

    _original_print("")

    if config.NEVER_SKIP_ARTISTS:
        print("   \u2022 The following artists will never be skipped:")
        for artist in config.NEVER_SKIP_ARTISTS:
            name = artist.get("name") or artist.get("id", "Unknown")
            print(f"     - {name}")
    else:
        print("   \u2022 No artists are configured to never be skipped.")

    _original_print("")

    while True:
        try:
            # Manual pause from the tray
            if utils.skipping_paused:
                print("\u23f8\ufe0f Skipping manually paused via tray.")
                utils.interruptible_sleep(config.POLL_INTERVAL_SECONDS)
                continue

            # Remote Dropbox toggle
            if not is_skipping_enabled():
                print("\U0001f6ab Remote control: skipping temporarily disabled.")
                utils.interruptible_sleep(config.POLL_INTERVAL_SECONDS)
                continue

            track = get_current_track()

            # Nothing playing or invalid data
            if not track or not track.get('artist') or not track.get('id'):
                print("\U0001f3a7 Nothing is playing right now.")
                utils.interruptible_sleep(config.POLL_INTERVAL_SECONDS)
                continue

            if not track['artist'] or not track['id']:
                utils.interruptible_sleep(config.POLL_INTERVAL_SECONDS)
                continue

            # Same song as last time
            if track['id'] == utils.last_checked_track_id:
                has_pending = _check_pending_recommendation(track)
                if has_pending:
                    remaining_ms = (utils.pending_recommendation_duration_ms / 2) - track.get("progress_ms", 0)
                    wait_s = max(5, min(config.POLL_INTERVAL_SECONDS, remaining_ms / 1000 + 2))
                    print(f"\u23f8\ufe0f Same song ({track['name']}) \u2014 rechecking in {wait_s:.0f}s for recommendation")
                    utils.interruptible_sleep(wait_s)
                else:
                    print(f"\u23f8\ufe0f Same song as last time ({track['name']}) \u2014 skipping the check.")
                    utils.interruptible_sleep(config.POLL_INTERVAL_SECONDS)
                continue

            # New song — remember it
            utils.last_checked_track_id = track['id']
            utils.last_checked_timestamp = datetime.now(timezone.utc)

            # Clear temporary pause if song changed
            if utils.temp_pause_track_id and utils.temp_pause_track_id != track['id']:
                print("\U0001f513 Clearing temporary pause (song changed)")
                utils.temp_pause_track_id = None

            print(f"\U0001f3b5 Currently playing: {track['artist']} \u2013 {track['name']}")

            # Check for Smart Shuffle recommendations
            _check_recommendation(track)
            _check_pending_recommendation(track)

            # Temporarily paused for this specific song
            if utils.temp_pause_track_id == track['id']:
                print("\u23f8\ufe0f Skipping is temporarily paused for this song")
                utils.interruptible_sleep(config.POLL_INTERVAL_SECONDS)
                continue

            # Get latest scrobble date from Last.fm
            last_played = get_last_play_date(track['artist'], track['name'])
            if last_played:
                days_since = (datetime.now(timezone.utc) - last_played).days
                print(f"\u2139\ufe0f Last scrobble: {last_played.strftime('%Y-%m-%d')} - {days_since} days ago")

                cutoff = datetime.now(timezone.utc) - timedelta(days=config.SKIP_WINDOW_DAYS)
                if last_played > cutoff:
                    # Check never-skip list
                    if is_artist_never_skipped(track.get('artist_ids', [])):
                        print("\U0001f3a4 Artist is in never-skip list \u2014 not skipping")
                    # Check liked songs
                    elif config.ALWAYS_PLAY_LIKED_SONGS and is_track_liked(track['id']):
                        print("\U0001f49a Track is in Liked Songs \u2014 not skipping")
                    else:
                        print(f"\u23ed\ufe0f Already listened to {days_since} days ago \u2014 skipping")
                        was_paused = is_spotify_paused()
                        skip_current_track()
                        if was_paused:
                            time.sleep(1)
                            pause_spotify_playback()

                        # Track recent skip patterns
                        if config.ENABLE_RESTART_PATTERN:
                            recent_skip_days.append(days_since)
                            if len(recent_skip_days) > config.RESTART_PATTERN_SONG_COUNT:
                                recent_skip_days.pop(0)

                            if (
                                len(recent_skip_days) == config.RESTART_PATTERN_SONG_COUNT
                                and max(recent_skip_days) - min(recent_skip_days) <= config.RESTART_PATTERN_DAY_DIFF
                            ):
                                print(f"\u26a0\ufe0f Detected repeating pattern ({config.RESTART_PATTERN_SONG_COUNT} skips within \u00b1{config.RESTART_PATTERN_DAY_DIFF} day) \u2014 restarting playlist...")
                                restart_playlist()
                                recent_skip_days.clear()

                        time.sleep(3)
                        print("\U0001f501 Checking the next song right away...")
                        continue
                else:
                    print("\u2705 The last scrobble is older than the window \u2014 not skipping.")
            else:
                print("\u2139\ufe0f There's no scrobble for this song \u2014 not skipping.")

        except KeyboardInterrupt:
            print("\n\U0001f44b Stopped by user.")
            break
        except Exception as e:
            print(f"\u2757 Unexpected error: {e}")
            utils.interruptible_sleep(config.POLL_INTERVAL_SECONDS)

        # Standard pause between check cycles (shorter if a recommendation notification is pending)
        if utils.pending_recommendation_track is not None and utils.pending_recommendation_duration_ms > 0:
            remaining_ms = (utils.pending_recommendation_duration_ms / 2) - track.get("progress_ms", 0)
            wait_s = max(5, min(config.POLL_INTERVAL_SECONDS, remaining_ms / 1000 + 2))
            utils.interruptible_sleep(wait_s)
        else:
            utils.interruptible_sleep(config.POLL_INTERVAL_SECONDS)


# -----------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------

def _idle_loop():
    """
    Main-thread idle loop. Checks for GUI events (e.g. open settings)
    and dispatches PySide6 windows. Qt requires the main thread.
    """
    from spotify_auto_skipper.gui.theme import ensure_app
    app = ensure_app()

    while not utils.should_exit.is_set():
        if open_settings_event.wait(timeout=1):
            open_settings_event.clear()
            try:
                from spotify_auto_skipper.gui.settings_window import SettingsWindow
                SettingsWindow.open()
                app.exec()
            except Exception as e:
                print(f"\u2757 Error opening settings: {e}")
            # Drain any clicks that arrived while the window was open
            open_settings_event.clear()


def main():
    _mutex = _check_single_instance()

    # First-run wizard (before logging, needs console stdout for Qt)
    import sys
    cfg = config.Config()
    if "--wizard" in sys.argv or not cfg.exists():
        from spotify_auto_skipper.gui.setup_wizard import SetupWizard
        wizard = SetupWizard()
        wizard.run()  # Blocks until complete or exits if cancelled

    _setup_logging()
    load_config()

    # Log migration message now that logging is set up (UTF-8 safe)
    if getattr(cfg, '_migrated', False):
        print(f"\U0001f4e6 Migrated config from config.ini to {cfg.json_path}")

    _print_startup_header()

    create_tray_icon()

    # Run main_loop in a daemon thread so main thread can handle GUI
    import threading
    worker = threading.Thread(target=main_loop, daemon=True)
    worker.start()

    _idle_loop()
