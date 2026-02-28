import json
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
    Always used for key.bin and paths.json (stay local for security)."""
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    path = os.path.join(appdata, "SpotifyAutoSkipper")
    os.makedirs(path, exist_ok=True)
    return path


# -----------------------------------------------------------------
# paths.json — stored in %APPDATA%, points to config & log dirs
# -----------------------------------------------------------------

_PATHS_FILE = None  # lazy-init
_paths_cache = None


def _get_paths_file():
    global _PATHS_FILE
    if _PATHS_FILE is None:
        _PATHS_FILE = os.path.join(get_appdata_dir(), "paths.json")
    return _PATHS_FILE


def _load_paths():
    """Load paths.json from %APPDATA%. Returns dict with config_dir, log_dir."""
    global _paths_cache
    if _paths_cache is not None:
        return _paths_cache

    paths_file = _get_paths_file()
    defaults = {
        "config_dir": get_appdata_dir(),
        "log_dir": os.path.join(get_appdata_dir(), "logs"),
    }

    if os.path.exists(paths_file):
        try:
            with open(paths_file, "r", encoding="utf-8") as f:
                stored = json.load(f)
            defaults.update({k: v for k, v in stored.items() if v})
        except (json.JSONDecodeError, OSError):
            pass
    else:
        # Backward compat: if config file exists next to exe, use that (portable mode)
        exe_dir = get_exe_dir()
        if (os.path.exists(os.path.join(exe_dir, "spotify-auto-skipper-config.json"))
                or os.path.exists(os.path.join(exe_dir, "config.json"))):
            defaults["config_dir"] = exe_dir

    # Normalize all paths to use consistent OS separators
    defaults = {k: os.path.normpath(v) for k, v in defaults.items()}

    _paths_cache = defaults
    return _paths_cache


def _save_paths(paths):
    """Save paths.json to %APPDATA%."""
    global _paths_cache
    paths = {k: os.path.normpath(v) for k, v in paths.items()}
    _paths_cache = dict(paths)
    paths_file = _get_paths_file()
    with open(paths_file, "w", encoding="utf-8") as f:
        json.dump(paths, f, indent=2)


# -----------------------------------------------------------------
# Public directory getters
# -----------------------------------------------------------------

def get_config_dir():
    """Returns the directory where the config file is stored."""
    paths = _load_paths()
    d = os.path.normpath(paths["config_dir"])
    os.makedirs(d, exist_ok=True)
    return d


def get_log_dir():
    """Returns the directory where log files are stored."""
    paths = _load_paths()
    d = os.path.normpath(paths["log_dir"])
    os.makedirs(d, exist_ok=True)
    return d


def set_config_dir(new_dir):
    """Change the config directory and persist to paths.json."""
    new_dir = os.path.normpath(new_dir)
    os.makedirs(new_dir, exist_ok=True)
    paths = _load_paths()
    paths["config_dir"] = new_dir
    _save_paths(paths)


def set_log_dir(new_dir):
    """Change the log directory and persist to paths.json."""
    new_dir = os.path.normpath(new_dir)
    os.makedirs(new_dir, exist_ok=True)
    paths = _load_paths()
    paths["log_dir"] = new_dir
    _save_paths(paths)


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
