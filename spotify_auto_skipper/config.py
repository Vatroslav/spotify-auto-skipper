import json
import os
import configparser
import threading

from spotify_auto_skipper.utils import get_exe_dir, get_config_dir, set_config_dir
from spotify_auto_skipper.encryption import CredentialEncryption

# Default values for all config keys
CONFIG_DEFAULTS = {
    "lastfm_username": "",
    "lastfm_api_key": "",
    "spotify_client_id": "",
    "spotify_client_secret": "",
    "spotify_refresh_token": "",
    "skip_window_days": 60,
    "poll_interval_seconds": 120,
    "enable_restart_pattern": True,
    "restart_pattern_song_count": 5,
    "restart_pattern_day_diff": 2,
    "dummy_playlist_id": "37i9dQZF1DX0XUsuxWHRQd",
    "remote_control_url": "ON",
    "always_play_liked_songs": True,
    "enable_never_skip_artists": True,
    "never_skip_artists": [],
    "log_retention_days": 30,
    "start_with_windows": False,
    "enable_recommendation_notifications": True,
}

# Keys that hold sensitive credentials (for future encryption, Issue #21)
SENSITIVE_KEYS = {"spotify_client_secret", "spotify_refresh_token", "lastfm_api_key"}

# Mapping from old .ini (section, key) to new flat JSON key
_INI_TO_JSON_MAP = {
    ("LastFM", "username"): "lastfm_username",
    ("LastFM", "api_key"): "lastfm_api_key",
    ("Spotify", "client_id"): "spotify_client_id",
    ("Spotify", "client_secret"): "spotify_client_secret",
    ("Spotify", "refresh_token"): "spotify_refresh_token",
    ("Settings", "skip_window_days"): "skip_window_days",
    ("Settings", "poll_interval_seconds"): "poll_interval_seconds",
    ("Settings", "enable_restart_pattern"): "enable_restart_pattern",
    ("Settings", "restart_pattern_song_count"): "restart_pattern_song_count",
    ("Settings", "restart_pattern_day_diff"): "restart_pattern_day_diff",
    ("Settings", "dummy_playlist_id"): "dummy_playlist_id",
    ("Settings", "remote_control_url"): "remote_control_url",
    ("Settings", "always_play_liked_songs"): "always_play_liked_songs",
    ("Settings", "never_skip_artist_ids"): "never_skip_artist_ids",  # old string, migrated in _enforce_constraints
    ("Settings", "log_retention_days"): "log_retention_days",
}

# Keys that should be parsed as int
_INT_KEYS = {
    "skip_window_days", "poll_interval_seconds",
    "restart_pattern_song_count", "restart_pattern_day_diff",
    "log_retention_days",
}

# Keys that should be parsed as bool
_BOOL_KEYS = {
    "enable_restart_pattern", "always_play_liked_songs", "start_with_windows",
    "enable_recommendation_notifications",
}


_CONFIG_FILENAME = "spotify-auto-skipper-config.json"
_LEGACY_CONFIG_FILENAME = "config.json"


class Config:
    """
    Singleton config manager.
    Loads from JSON in %APPDATA%/SpotifyAutoSkipper/spotify-auto-skipper-config.json.
    Falls back to legacy .ini migration if JSON doesn't exist.
    Auto-renames old config.json to new name on first load.
    """
    _instance = None
    _lock = threading.RLock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._data = dict(CONFIG_DEFAULTS)
            cls._instance._loaded = False
            cls._instance._encryption = CredentialEncryption()
        return cls._instance

    @property
    def json_path(self):
        return os.path.join(get_config_dir(), _CONFIG_FILENAME)

    @property
    def legacy_ini_path(self):
        return os.path.join(get_exe_dir(), "config.ini")

    @property
    def _legacy_json_path(self):
        return os.path.join(get_config_dir(), _LEGACY_CONFIG_FILENAME)

    def exists(self):
        """Check if any config file (JSON, legacy JSON, or legacy .ini) exists."""
        return (os.path.exists(self.json_path)
                or os.path.exists(self._legacy_json_path)
                or os.path.exists(self.legacy_ini_path))

    def load(self):
        """Load config: JSON first, fall back to .ini migration, fall back to defaults."""
        with self._lock:
            # Auto-rename old config.json → spotify-auto-skipper-config.json
            if not os.path.exists(self.json_path) and os.path.exists(self._legacy_json_path):
                try:
                    os.rename(self._legacy_json_path, self.json_path)
                except OSError:
                    pass

            if os.path.exists(self.json_path):
                self._load_json()
            elif os.path.exists(self.legacy_ini_path):
                self._migrate_from_ini()
            else:
                self._data = dict(CONFIG_DEFAULTS)
            self._enforce_constraints()
            self._loaded = True

    def _load_json(self):
        with open(self.json_path, "r", encoding="utf-8") as f:
            stored = json.load(f)
        # Merge with defaults so new keys added in future versions get their defaults
        self._data = {**CONFIG_DEFAULTS, **stored}
        # Decrypt sensitive values transparently
        for key in SENSITIVE_KEYS:
            if key in self._data and self._data[key]:
                self._data[key] = self._encryption.decrypt(self._data[key])

    def _migrate_from_ini(self):
        """Read legacy config.ini, convert to JSON structure, save as JSON."""
        ini = configparser.ConfigParser()
        ini.read(self.legacy_ini_path)

        self._data = dict(CONFIG_DEFAULTS)

        for (section, key), json_key in _INI_TO_JSON_MAP.items():
            try:
                if json_key in _INT_KEYS:
                    self._data[json_key] = ini.getint(section, key)
                elif json_key in _BOOL_KEYS:
                    self._data[json_key] = ini.getboolean(section, key)
                else:
                    self._data[json_key] = ini.get(section, key)
            except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
                pass  # Keep default

        self.save()
        self._migrated = True  # Flag for app.py to log after logging is set up

    def _enforce_constraints(self):
        """Enforce minimum/maximum values and data format migrations."""
        self._data["poll_interval_seconds"] = max(5, int(self._data.get("poll_interval_seconds", 120)))
        self._data["skip_window_days"] = max(1, int(self._data.get("skip_window_days", 60)))
        self._data["log_retention_days"] = max(1, int(self._data.get("log_retention_days", 30)))

        # Migrate old "never_skip_artist_ids" string to new "never_skip_artists" list
        old_val = self._data.pop("never_skip_artist_ids", None)
        if old_val and isinstance(old_val, str) and old_val.strip():
            ids = [aid.strip() for aid in old_val.split(",") if aid.strip()]
            existing = self._data.get("never_skip_artists", [])
            existing_ids = {a["id"] for a in existing if isinstance(a, dict)}
            for aid in ids:
                if aid not in existing_ids:
                    existing.append({"id": aid, "name": ""})
            self._data["never_skip_artists"] = existing

        # Ensure never_skip_artists is always a list
        if not isinstance(self._data.get("never_skip_artists"), list):
            self._data["never_skip_artists"] = []

    def save(self):
        with self._lock:
            # Encrypt sensitive values for storage
            to_write = dict(self._data)
            for key in SENSITIVE_KEYS:
                if key in to_write and to_write[key]:
                    to_write[key] = self._encryption.encrypt(to_write[key])
            with open(self.json_path, "w", encoding="utf-8") as f:
                json.dump(to_write, f, indent=2)

    def get(self, key, default=None):
        with self._lock:
            if default is not None:
                return self._data.get(key, default)
            return self._data.get(key, CONFIG_DEFAULTS.get(key))

    def set(self, key, value):
        with self._lock:
            self._data[key] = value

    def reload(self):
        self.load()

    def as_dict(self):
        with self._lock:
            return dict(self._data)

    def move_to(self, new_dir):
        """Move config to a new directory. Returns True on success."""
        with self._lock:
            old_path = self.json_path
            set_config_dir(new_dir)
            new_path = self.json_path

            if os.path.normcase(os.path.normpath(old_path)) == \
               os.path.normcase(os.path.normpath(new_path)):
                return True  # Already there

            # Save to new location
            self.save()

            # Remove old file
            try:
                if os.path.exists(old_path):
                    os.remove(old_path)
            except OSError:
                pass

            return True


# -----------------------------------------------------------------
# Module-level convenience access (backward compatible)
# -----------------------------------------------------------------
# These are populated by _load_module_vars() after Config.load()
# and used by other modules via: from spotify_auto_skipper.config import CLIENT_ID

LASTFM_API_KEY = ""
LASTFM_USER = ""
CLIENT_ID = ""
CLIENT_SECRET = ""
REFRESH_TOKEN = ""
SKIP_WINDOW_DAYS = 60
POLL_INTERVAL_SECONDS = 120
ENABLE_RESTART_PATTERN = True
RESTART_PATTERN_SONG_COUNT = 5
RESTART_PATTERN_DAY_DIFF = 2
DUMMY_PLAYLIST_ID = "37i9dQZF1DX0XUsuxWHRQd"
REMOTE_CONTROL_URL = "ON"
ALWAYS_PLAY_LIKED_SONGS = True
NEVER_SKIP_ARTISTS = []
LOG_RETENTION_DAYS = 30
ENABLE_RECOMMENDATION_NOTIFICATIONS = True
NEVER_SKIP_ARTIST_IDS_LIST = []
NEVER_SKIP_ARTIST_IDS_SET = set()


def load_config():
    """Load config and populate module-level variables for backward compat."""
    global LASTFM_API_KEY, LASTFM_USER
    global CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN
    global SKIP_WINDOW_DAYS, POLL_INTERVAL_SECONDS
    global ENABLE_RESTART_PATTERN, RESTART_PATTERN_SONG_COUNT, RESTART_PATTERN_DAY_DIFF
    global DUMMY_PLAYLIST_ID, REMOTE_CONTROL_URL
    global ALWAYS_PLAY_LIKED_SONGS, ENABLE_NEVER_SKIP_ARTISTS, NEVER_SKIP_ARTISTS, LOG_RETENTION_DAYS
    global ENABLE_RECOMMENDATION_NOTIFICATIONS
    global NEVER_SKIP_ARTIST_IDS_LIST, NEVER_SKIP_ARTIST_IDS_SET

    cfg = Config()
    cfg.load()

    LASTFM_API_KEY = cfg.get("lastfm_api_key")
    LASTFM_USER = cfg.get("lastfm_username")
    CLIENT_ID = cfg.get("spotify_client_id")
    CLIENT_SECRET = cfg.get("spotify_client_secret")
    REFRESH_TOKEN = cfg.get("spotify_refresh_token")
    SKIP_WINDOW_DAYS = cfg.get("skip_window_days")
    POLL_INTERVAL_SECONDS = cfg.get("poll_interval_seconds")
    ENABLE_RESTART_PATTERN = cfg.get("enable_restart_pattern")
    RESTART_PATTERN_SONG_COUNT = cfg.get("restart_pattern_song_count")
    RESTART_PATTERN_DAY_DIFF = cfg.get("restart_pattern_day_diff")
    DUMMY_PLAYLIST_ID = cfg.get("dummy_playlist_id")
    REMOTE_CONTROL_URL = cfg.get("remote_control_url")
    ALWAYS_PLAY_LIKED_SONGS = cfg.get("always_play_liked_songs")
    ENABLE_NEVER_SKIP_ARTISTS = cfg.get("enable_never_skip_artists")
    NEVER_SKIP_ARTISTS = cfg.get("never_skip_artists", [])
    LOG_RETENTION_DAYS = cfg.get("log_retention_days")
    ENABLE_RECOMMENDATION_NOTIFICATIONS = cfg.get("enable_recommendation_notifications")

    # Build ID list/set from the artists list
    NEVER_SKIP_ARTIST_IDS_LIST = [a["id"] for a in NEVER_SKIP_ARTISTS if isinstance(a, dict) and a.get("id")]
    NEVER_SKIP_ARTIST_IDS_SET = set(NEVER_SKIP_ARTIST_IDS_LIST)
