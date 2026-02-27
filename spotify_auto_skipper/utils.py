import os
import sys
import threading


def get_exe_dir():
    """Directory where the .exe or .py script lives."""
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller .exe
        return os.path.dirname(os.path.abspath(sys.executable))
    else:
        # Running as script — use the script's directory
        return os.path.dirname(os.path.abspath(sys.argv[0]))


def get_appdata_dir():
    """Returns %APPDATA%/SpotifyAutoSkipper, creates if needed."""
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    path = os.path.join(appdata, "SpotifyAutoSkipper")
    os.makedirs(path, exist_ok=True)
    return path


# -----------------------------------------------------------------
# Shared application state (accessed by tray.py and app.py)
# -----------------------------------------------------------------
should_exit = threading.Event()
check_now_event = threading.Event()
skipping_paused = False
temp_pause_track_id = None
last_checked_track_id = None
last_checked_timestamp = None


def interruptible_sleep(seconds):
    """Sleep that can be interrupted by the Check Now tray action."""
    check_now_event.wait(timeout=seconds)
    check_now_event.clear()
