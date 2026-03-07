from datetime import datetime, timezone
import requests

from spotify_auto_skipper import config
from spotify_auto_skipper.spotify_api import CredentialError


def get_last_play_date(artist, track):
    """
    Returns the datetime (UTC) of the last scrobble for the given (artist, track)
    from Last.fm, or None if there are no scrobbles.
    Uses 'limit=1' to only fetch the latest scrobble.
    """
    try:
        r = requests.get(
            "https://ws.audioscrobbler.com/2.0/",
            params={
                "method": "user.gettrackscrobbles",
                "user": config.LASTFM_USER,
                "artist": artist,
                "track": track,
                "api_key": config.LASTFM_API_KEY,
                "format": "json",
                "limit": 1,
            },
            timeout=15,
        )
    except requests.RequestException as e:
        print(f"\u26a0\ufe0f [Last.fm] Network error: {e}")
        return None

    if r.status_code != 200:
        # Check for invalid API key
        try:
            err = r.json()
            if err.get("error") == 10:  # Last.fm error 10 = Invalid API key
                raise CredentialError(f"Invalid Last.fm API key. Please check your credentials.")
        except (ValueError, KeyError):
            pass
        print(f"\u26a0\ufe0f [Last.fm] Unexpected status {r.status_code}: {r.text}")
        return None

    data = r.json() or {}
    trackscrobbles = data.get("trackscrobbles", {})
    scrobbles = trackscrobbles.get("track")

    if not scrobbles:
        return None

    # If it's a list, take the first (latest) one
    if isinstance(scrobbles, list):
        latest = scrobbles[0]
        date_obj = latest.get("date", {})
        uts = date_obj.get("uts")
        if uts:
            try:
                return datetime.fromtimestamp(int(uts), tz=timezone.utc)
            except (ValueError, OSError):
                return None

    # If it's a single object (less common)
    if isinstance(scrobbles, dict):
        date_obj = scrobbles.get("date", {})
        uts = date_obj.get("uts")
        if uts:
            try:
                return datetime.fromtimestamp(int(uts), tz=timezone.utc)
            except (ValueError, OSError):
                return None

    return None
