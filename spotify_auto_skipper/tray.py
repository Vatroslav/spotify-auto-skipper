import os
import sys
import threading

from PIL import Image
import pystray

from spotify_auto_skipper import utils
from spotify_auto_skipper import APP_VERSION
from spotify_auto_skipper.utils import resource_path
from spotify_auto_skipper.spotify_api import get_current_track


# Event to signal the main thread to open the settings window (Issue #20)
open_settings_event = threading.Event()


def create_tray_icon():
    """
    Creates a tray icon using the app logo.
    Right click -> menu with pause, check now, open logs, exit.
    """

    # ---------------------------------------------------------
    # LOAD ICON from bundled assets
    # ---------------------------------------------------------
    img = Image.open(resource_path("assets/app.png")).convert("RGBA")
    img = img.resize((64, 64), Image.Resampling.LANCZOS)

    # ---------------------------------------------------------
    # MENU ACTIONS
    # ---------------------------------------------------------
    def toggle_skip(icon, item):
        utils.skipping_paused = not utils.skipping_paused
        state = "paused" if utils.skipping_paused else "resumed"
        print(f"\u23ef\ufe0f Skipping manually {state} from tray.")
        icon.update_menu()

    def pause_current_song(icon, item):
        try:
            track = get_current_track()
            if track and track.get('id'):
                utils.temp_pause_track_id = track['id']
                print(f"\U0001f3b5 Temporarily paused skipping for: {track['artist']} \u2013 {track['name']} (will resume on next song)")
            else:
                print("\u26a0\ufe0f No song currently playing to pause skipping for.")
        except Exception as e:
            print(f"\u2757 Failed to pause current song: {e}")
        icon.update_menu()

    def check_now(icon, item):
        utils.last_checked_track_id = None
        utils.check_now_event.set()
        print("\U0001f50d Check Now triggered from tray.")

    def open_logs(icon, item):
        os.startfile(utils.get_log_dir())

    def on_exit(icon, item):
        print("\U0001f6d1 Exit clicked from tray.")
        icon.stop()
        sys.stdout.flush()
        os._exit(0)

    def skip_label(item):
        return "\u23f8\ufe0f Resume Skipping" if utils.skipping_paused else "\u23ef\ufe0f Pause Skipping"

    def open_settings(icon, item):
        open_settings_event.set()
        print("\u2699\ufe0f Settings opened from tray.")

    menu = pystray.Menu(
        pystray.MenuItem(skip_label, toggle_skip),
        pystray.MenuItem("\U0001f3b5 Don't skip this song", pause_current_song),
        pystray.MenuItem("\U0001f50d Check Now", check_now),
        pystray.MenuItem("\u2699\ufe0f Settings...", open_settings, default=True),
        pystray.MenuItem("\U0001f4c1 Open Logs", open_logs),
        pystray.MenuItem("\u274c Exit", on_exit),
    )

    # ---------------------------------------------------------
    # RUN TRAY IN BACKGROUND THREAD
    # ---------------------------------------------------------
    icon = pystray.Icon("spotify_skipper", img, f"Spotify Auto-Skipper {APP_VERSION}", menu)
    utils.tray_icon = icon
    threading.Thread(target=icon.run, daemon=False).start()
