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


def resource_path(relative_path):
    """Get path to a bundled resource (works in dev and PyInstaller .exe)."""
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def get_appdata_dir():
    """Returns %APPDATA%/SpotifyAutoSkipper, creates if needed.
    Always used for key.bin (encryption key stays local for security)."""
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    path = os.path.join(appdata, "SpotifyAutoSkipper")
    os.makedirs(path, exist_ok=True)
    return path


# Cached config directory (set once at startup)
_config_dir = None


def get_config_dir():
    """Returns the directory where config.json is stored.
    Priority:
      1. Next to the .exe / script (portable mode, e.g. Dropbox)
      2. %APPDATA%/SpotifyAutoSkipper/ (default)
    """
    global _config_dir
    if _config_dir is not None:
        return _config_dir

    exe_dir = get_exe_dir()
    if os.path.exists(os.path.join(exe_dir, "config.json")):
        _config_dir = exe_dir
    else:
        _config_dir = get_appdata_dir()
    return _config_dir


def set_config_dir(path):
    """Override the config directory (used when moving config)."""
    global _config_dir
    os.makedirs(path, exist_ok=True)
    _config_dir = path


def is_portable_mode():
    """True if config.json lives next to the exe (not in %APPDATA%)."""
    return os.path.normcase(os.path.normpath(get_config_dir())) == \
           os.path.normcase(os.path.normpath(get_exe_dir()))


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
