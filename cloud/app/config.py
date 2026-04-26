"""
Configuration: env vars for secrets, SQLite for user-adjustable settings.
"""

import os

from app.database import get_all_settings, set_many_settings

# Settings that live in the database (user-adjustable)
CONFIG_DEFAULTS = {
    "skip_window_days": 60,
    "poll_interval_seconds": 120,
    "idle_threshold": 3,
    "idle_poll_interval_seconds": 600,
    "enable_restart_pattern": True,
    "restart_pattern_song_count": 5,
    "restart_pattern_day_diff": 2,
    "dummy_playlist_id": "37i9dQZF1DX0XUsuxWHRQd",
    "always_play_liked_songs": True,
    "enable_never_skip_artists": True,
    "log_retention_days": 30,
}

# Type mappings
_INT_KEYS = {
    "skip_window_days",
    "poll_interval_seconds",
    "idle_threshold",
    "idle_poll_interval_seconds",
    "restart_pattern_song_count",
    "restart_pattern_day_diff",
    "log_retention_days",
}
_BOOL_KEYS = {
    "enable_restart_pattern",
    "always_play_liked_songs",
    "enable_never_skip_artists",
}


def _parse_value(key: str, raw: str):
    """Parse a string value from the DB into its proper Python type."""
    if key in _INT_KEYS:
        try:
            return int(raw)
        except (ValueError, TypeError):
            return CONFIG_DEFAULTS.get(key, 0)
    if key in _BOOL_KEYS:
        return raw.lower() in ("true", "1", "yes") if isinstance(raw, str) else bool(raw)
    return raw


def _serialize_value(key: str, value) -> str:
    """Serialize a Python value for DB storage."""
    if key in _BOOL_KEYS:
        return "true" if value else "false"
    return str(value)


# ── Environment variables (secrets) ──────────────────────────────


def get_spotify_client_id() -> str:
    return os.environ.get("SPOTIFY_CLIENT_ID", "")


def get_spotify_client_secret() -> str:
    return os.environ.get("SPOTIFY_CLIENT_SECRET", "")


def get_lastfm_username() -> str:
    return os.environ.get("LASTFM_USERNAME", "")


def get_lastfm_api_key() -> str:
    return os.environ.get("LASTFM_API_KEY", "")


def get_lastfm_api_secret() -> str:
    return os.environ.get("LASTFM_API_SECRET", "")


def get_secret_key() -> str:
    key = os.environ.get("SECRET_KEY", "")
    if not key or len(key) < 32:
        raise RuntimeError(
            "SECRET_KEY env var must be set and at least 32 characters. "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )
    # Check for sufficient character diversity (reject low-entropy strings)
    unique_chars = len(set(key))
    if unique_chars < 10:
        raise RuntimeError(
            "SECRET_KEY has too little entropy (only %d unique characters). "
            'Generate a random one with: python -c "import secrets; print(secrets.token_urlsafe(32))"' % unique_chars
        )
    return key


def get_base_url() -> str:
    return os.environ.get("BASE_URL", "http://localhost:8000")


def get_allowed_spotify_user() -> str:
    """Spotify user ID whitelist. Empty string means no restriction."""
    return os.environ.get("ALLOWED_SPOTIFY_USER", "")


# ── Settings (from SQLite) ───────────────────────────────────────


async def load_settings() -> dict:
    """Load all settings, merging DB values with defaults."""
    stored = await get_all_settings()
    result = {}
    for key, default in CONFIG_DEFAULTS.items():
        if key in stored:
            result[key] = _parse_value(key, stored[key])
        else:
            result[key] = default
    return result


_RANGES = {
    "skip_window_days": (1, 365),
    "poll_interval_seconds": (5, 600),
    "idle_threshold": (1, 20),
    "idle_poll_interval_seconds": (60, 3600),
    "log_retention_days": (1, 365),
    "restart_pattern_song_count": (2, 20),
    "restart_pattern_day_diff": (0, 30),
}


async def save_settings(updates: dict) -> list[str]:
    """Save partial settings update to DB. Returns list of validation warnings."""
    warnings = []
    to_store = {}
    for key, value in updates.items():
        if key not in CONFIG_DEFAULTS:
            continue
        if key in _INT_KEYS:
            try:
                value = int(value)
            except (ValueError, TypeError):
                warnings.append(f"{key}: must be a number")
                continue
            if key in _RANGES:
                lo, hi = _RANGES[key]
                if value < lo or value > hi:
                    warnings.append(f"{key}: must be between {lo} and {hi}")
                    continue
        to_store[key] = _serialize_value(key, value)
    if to_store:
        await set_many_settings(to_store)
    return warnings


async def seed_defaults():
    """Seed default settings into DB if they don't exist."""
    stored = await get_all_settings()
    missing = {}
    for key, value in CONFIG_DEFAULTS.items():
        if key not in stored:
            missing[key] = _serialize_value(key, value)
    if missing:
        await set_many_settings(missing)
