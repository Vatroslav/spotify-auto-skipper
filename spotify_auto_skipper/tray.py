import os
import sys
import threading

from PIL import Image, ImageDraw
import pystray

from spotify_auto_skipper import utils
from spotify_auto_skipper import APP_VERSION
from spotify_auto_skipper.spotify_api import get_current_track


# Event to signal the main thread to open the settings window (Issue #20)
open_settings_event = threading.Event()


def create_tray_icon():
    """
    Creates a tray icon (next to the clock) that looks like the Spotify logo:
    - Green Background (#1DB954)
    - Three white curved Spotify lines
    - Black skip symbol over them
    Right click -> menu with pause, check now, open logs, exit.
    """

    # ---------------------------------------------------------
    # CREATE ICON (64x64, tray automatically scales)
    # ---------------------------------------------------------
    size = 64
    img = Image.new("RGB", (size, size), color=(29, 185, 84))  # Spotify green
    draw = ImageDraw.Draw(img)

    # Three white curved lines (Spotify "waves")
    wave_color = (255, 255, 255)
    for i, offset in enumerate([10, 20, 30]):
        draw.arc([10, offset, 54, offset + 25], start=200, end=340, fill=wave_color, width=4)

    # Black skip symbol
    skip_color = (0, 0, 0)
    draw.polygon([(36, 20), (46, 32), (36, 44)], fill=skip_color)
    draw.polygon([(46, 20), (56, 32), (46, 44)], fill=skip_color)
    draw.rectangle([57, 20, 59, 44], fill=skip_color)

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
        logs_path = os.path.join(utils.get_exe_dir(), "logs")
        os.startfile(logs_path)

    def on_exit(icon, item):
        print("\U0001f6d1 Exit clicked from tray.")
        icon.stop()
        sys.stdout.flush()
        os._exit(0)

    def skip_label(item):
        return "\u23f8\ufe0f Resume Skipping" if utils.skipping_paused else "\u23ef\ufe0f Pause Skipping"

    menu = pystray.Menu(
        pystray.MenuItem(skip_label, toggle_skip),
        pystray.MenuItem("\U0001f3b5 Don't skip this song", pause_current_song),
        pystray.MenuItem("\U0001f50d Check Now", check_now),
        pystray.MenuItem("\U0001f4c1 Open Logs", open_logs),
        pystray.MenuItem("\u274c Exit", on_exit),
    )

    # ---------------------------------------------------------
    # RUN TRAY IN BACKGROUND THREAD
    # ---------------------------------------------------------
    icon = pystray.Icon("spotify_skipper", img, f"Spotify Auto-Skipper {APP_VERSION}", menu)
    threading.Thread(target=icon.run, daemon=False).start()
