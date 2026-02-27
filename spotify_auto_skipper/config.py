import os
import configparser
from spotify_auto_skipper.utils import get_exe_dir

# Load configuration from config.ini
_config = configparser.ConfigParser()
_config.read(os.path.join(get_exe_dir(), "config.ini"))

# Last.fm
LASTFM_API_KEY = _config.get("LastFM", "api_key")
LASTFM_USER = _config.get("LastFM", "username")

# Spotify
CLIENT_ID = _config.get("Spotify", "client_id")
CLIENT_SECRET = _config.get("Spotify", "client_secret")
REFRESH_TOKEN = _config.get("Spotify", "refresh_token")

# Settings
SKIP_WINDOW_DAYS = _config.getint("Settings", "skip_window_days", fallback=60)
POLL_INTERVAL_SECONDS = max(5, _config.getint("Settings", "poll_interval_seconds", fallback=120))
ENABLE_RESTART_PATTERN = _config.getboolean("Settings", "enable_restart_pattern", fallback=True)
RESTART_PATTERN_SONG_COUNT = _config.getint("Settings", "restart_pattern_song_count", fallback=5)
RESTART_PATTERN_DAY_DIFF = _config.getint("Settings", "restart_pattern_day_diff", fallback=2)
DUMMY_PLAYLIST_ID = _config.get("Settings", "dummy_playlist_id", fallback="37i9dQZF1DX0XUsuxWHRQd")
REMOTE_CONTROL_URL = _config.get("Settings", "remote_control_url", fallback="ON")
ALWAYS_PLAY_LIKED_SONGS = _config.getboolean("Settings", "always_play_liked_songs", fallback=True)
NEVER_SKIP_ARTIST_IDS = _config.get("Settings", "never_skip_artist_ids", fallback="")
LOG_RETENTION_DAYS = _config.getint("Settings", "log_retention_days", fallback=30)

# Parse comma-separated artist IDs
if NEVER_SKIP_ARTIST_IDS:
    NEVER_SKIP_ARTIST_IDS_LIST = [aid.strip() for aid in NEVER_SKIP_ARTIST_IDS.split(",") if aid.strip()]
    NEVER_SKIP_ARTIST_IDS_SET = set(NEVER_SKIP_ARTIST_IDS_LIST)
else:
    NEVER_SKIP_ARTIST_IDS_LIST = []
    NEVER_SKIP_ARTIST_IDS_SET = set()
