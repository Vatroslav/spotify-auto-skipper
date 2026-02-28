import time
import base64
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import requests

from spotify_auto_skipper import config

# Token state
SPOTIFY_TOKEN = None
TOKEN_EXPIRES_AT = datetime.now(timezone.utc)

# Rate limiting configuration
RATE_LIMIT_MAX_RETRIES = 3
RATE_LIMIT_RETRY_DELAYS = [5, 10, 20]  # seconds


# -----------------------------------------------------------------
# Authentication
# -----------------------------------------------------------------

def refresh_access_token():
    """
    Request a new 'access_token' from Spotify using 'refresh_token'.
    Spotify expects a Basic auth header with Base64(ClientID:ClientSecret).
    'expires_in' is about 3600s — we refresh 100s early to avoid edge cases.
    """
    global SPOTIFY_TOKEN, TOKEN_EXPIRES_AT

    auth_header = base64.b64encode(
        f"{config.CLIENT_ID}:{config.CLIENT_SECRET}".encode()
    ).decode()

    try:
        r = requests.post(
            "https://accounts.spotify.com/api/token",
            headers={
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": config.REFRESH_TOKEN,
            },
            timeout=15,
        )
    except requests.RequestException as e:
        print(f"\u26a0\ufe0f [Spotify] Network error refreshing token: {e}")
        return

    if r.status_code != 200:
        raise RuntimeError(f"Failed to refresh token (HTTP {r.status_code}): {r.text}")

    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"No access_token in response: {data}")

    SPOTIFY_TOKEN = data["access_token"]

    expires_in = int(data.get("expires_in", 3600))
    TOKEN_EXPIRES_AT = datetime.now(timezone.utc) + timedelta(seconds=max(0, expires_in - 100))

    print("\U0001f504 [Spotify] Access token refreshed.")


def get_spotify_token():
    """Returns a valid Spotify access_token, refreshing if needed."""
    global SPOTIFY_TOKEN
    if SPOTIFY_TOKEN is None or datetime.now(timezone.utc) >= TOKEN_EXPIRES_AT:
        refresh_access_token()
    return SPOTIFY_TOKEN


# -----------------------------------------------------------------
# HTTP wrappers with rate-limit retry
# -----------------------------------------------------------------

def spotify_get(url, params=None):
    """GET wrapper with exponential backoff on 429."""
    for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
        try:
            token = get_spotify_token()
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params=params or {},
                timeout=15,
            )
        except requests.RequestException as e:
            print(f"\u26a0\ufe0f [Spotify] GET network error (attempt {attempt + 1}): {e}")
            if attempt < RATE_LIMIT_MAX_RETRIES:
                time.sleep(RATE_LIMIT_RETRY_DELAYS[min(attempt, len(RATE_LIMIT_RETRY_DELAYS) - 1)])
                continue
            return None

        if response.status_code == 429 and attempt < RATE_LIMIT_MAX_RETRIES:
            delay_index = min(attempt, len(RATE_LIMIT_RETRY_DELAYS) - 1)
            try:
                retry_after = int(response.headers.get("Retry-After", RATE_LIMIT_RETRY_DELAYS[delay_index]))
            except (ValueError, TypeError):
                retry_after = RATE_LIMIT_RETRY_DELAYS[delay_index]
            wait_time = min(retry_after, RATE_LIMIT_RETRY_DELAYS[delay_index])
            print(f"\u26a0\ufe0f [Spotify] Rate limited (429). Waiting {wait_time}s before retry {attempt + 1}/{RATE_LIMIT_MAX_RETRIES}...")
            time.sleep(wait_time)
            continue

        return response

    return response


def spotify_post(url, params=None, data=None):
    """POST wrapper with exponential backoff on 429."""
    for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
        try:
            token = get_spotify_token()
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params=params or {},
                data=data or {},
                timeout=15,
            )
        except requests.RequestException as e:
            print(f"\u26a0\ufe0f [Spotify] POST network error (attempt {attempt + 1}): {e}")
            if attempt < RATE_LIMIT_MAX_RETRIES:
                time.sleep(RATE_LIMIT_RETRY_DELAYS[min(attempt, len(RATE_LIMIT_RETRY_DELAYS) - 1)])
                continue
            return None

        if response.status_code == 429 and attempt < RATE_LIMIT_MAX_RETRIES:
            delay_index = min(attempt, len(RATE_LIMIT_RETRY_DELAYS) - 1)
            try:
                retry_after = int(response.headers.get("Retry-After", RATE_LIMIT_RETRY_DELAYS[delay_index]))
            except (ValueError, TypeError):
                retry_after = RATE_LIMIT_RETRY_DELAYS[delay_index]
            wait_time = min(retry_after, RATE_LIMIT_RETRY_DELAYS[delay_index])
            print(f"\u26a0\ufe0f [Spotify] Rate limited (429). Waiting {wait_time}s before retry {attempt + 1}/{RATE_LIMIT_MAX_RETRIES}...")
            time.sleep(wait_time)
            continue

        return response

    return response


def spotify_put(url, params=None, data=None):
    """PUT wrapper with exponential backoff on 429."""
    for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
        try:
            token = get_spotify_token()
            response = requests.put(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                params=params or {},
                json=data or {},
                timeout=15,
            )
        except requests.RequestException as e:
            print(f"\u26a0\ufe0f [Spotify] PUT network error (attempt {attempt + 1}): {e}")
            if attempt < RATE_LIMIT_MAX_RETRIES:
                time.sleep(RATE_LIMIT_RETRY_DELAYS[min(attempt, len(RATE_LIMIT_RETRY_DELAYS) - 1)])
                continue
            return None

        if response.status_code == 429 and attempt < RATE_LIMIT_MAX_RETRIES:
            delay_index = min(attempt, len(RATE_LIMIT_RETRY_DELAYS) - 1)
            try:
                retry_after = int(response.headers.get("Retry-After", RATE_LIMIT_RETRY_DELAYS[delay_index]))
            except (ValueError, TypeError):
                retry_after = RATE_LIMIT_RETRY_DELAYS[delay_index]
            wait_time = min(retry_after, RATE_LIMIT_RETRY_DELAYS[delay_index])
            print(f"\u26a0\ufe0f [Spotify] Rate limited (429). Waiting {wait_time}s before retry {attempt + 1}/{RATE_LIMIT_MAX_RETRIES}...")
            time.sleep(wait_time)
            continue

        return response

    return response


# -----------------------------------------------------------------
# Track detection & control
# -----------------------------------------------------------------

def get_current_track():
    """
    Returns a dict with info about the currently playing song:
    {"id", "name", "artist", "artist_ids"}, or None if nothing is playing.
    """
    r = spotify_get("https://api.spotify.com/v1/me/player/currently-playing")
    if r is None:
        return None

    if r.status_code == 204:
        return None
    if r.status_code != 200:
        print(f"\u26a0\ufe0f [Spotify] Unexpected status {r.status_code}: {r.text}")
        return None

    data = r.json() or {}
    item = data.get("item")
    if not item:
        return None

    artists = item.get("artists") or []
    artist_name = artists[0]["name"] if artists else None
    artist_ids = [artist["id"] for artist in artists if artist.get("id")]
    track_name = item.get("name")
    track_id = item.get("id")

    if track_id and artist_name and track_name:
        return {"id": track_id, "name": track_name, "artist": artist_name, "artist_ids": artist_ids}

    return None


def skip_current_track():
    """Send a command to Spotify to skip to the next song."""
    r = spotify_post("https://api.spotify.com/v1/me/player/next")
    if r is None:
        print("\u26a0\ufe0f [Spotify] Skip failed (network error)")
        return
    if r.status_code not in (200, 202, 204):
        print(f"\u26a0\ufe0f [Spotify] Skip failed (HTTP {r.status_code}): {r.text}")


def is_spotify_paused():
    r = spotify_get("https://api.spotify.com/v1/me/player")
    if r is None or r.status_code != 200:
        return False
    data = r.json() or {}
    return not data.get("is_playing", True)


def pause_spotify_playback():
    r = spotify_put("https://api.spotify.com/v1/me/player/pause")
    if r is None:
        print("\u26a0\ufe0f [Spotify] Failed to pause after skip (network error)")
        return
    if r.status_code not in (200, 202, 204):
        print(f"\u26a0\ufe0f [Spotify] Failed to pause after skip (HTTP {r.status_code}): {r.text}")


def restart_playlist():
    """Restart the current playlist (shuffle on) to break repeating patterns."""
    try:
        r = spotify_get("https://api.spotify.com/v1/me/player/currently-playing")
        if r is None or r.status_code != 200:
            print("\u26a0\ufe0f [Spotify] Cannot get current playback context")
            return
        data = r.json()
        context = data.get("context", {})
        context_uri = context.get("uri")
        if not context_uri:
            print("\u26a0\ufe0f [Spotify] No playlist context found \u2014 cannot restart.")
            return

        print(f"\U0001f501 Restarting playlist: {context_uri}")
        spotify_put("https://api.spotify.com/v1/me/player/play",
            data={"context_uri": f"spotify:playlist:{config.DUMMY_PLAYLIST_ID}"})
        time.sleep(1)

        spotify_put("https://api.spotify.com/v1/me/player/shuffle", params={"state": "true"})
        time.sleep(1)

        spotify_put("https://api.spotify.com/v1/me/player/play", data={"context_uri": context_uri})
        print("\u2705 Playlist restarted successfully.")
    except Exception as e:
        print(f"\u2757 Failed to restart playlist: {e}")


def _normalize_remote_url(url):
    """Convert Dropbox/Google Drive sharing URLs to direct-download URLs."""
    parsed = urlparse(url)

    # Dropbox: use raw=1 to get plain-text content instead of HTML preview
    if parsed.hostname and "dropbox.com" in parsed.hostname:
        qs = parse_qs(parsed.query, keep_blank_values=True)
        qs.pop("dl", None)
        qs["raw"] = ["1"]
        new_query = urlencode(qs, doseq=True)
        return urlunparse(parsed._replace(query=new_query))

    # Google Drive: convert /file/d/ID/... to /uc?export=download&id=ID
    if parsed.hostname and "drive.google.com" in parsed.hostname:
        m = re.search(r"/file/d/([^/]+)", parsed.path)
        if m:
            file_id = m.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"

    return url


def is_skipping_enabled():
    """Checks the Dropbox remote_control.txt file; returns True if ON."""
    if not config.REMOTE_CONTROL_URL:
        print("\u26a0\ufe0f [Remote Control] No REMOTE_CONTROL_URL set.")
        return True
    try:
        url = _normalize_remote_url(config.REMOTE_CONTROL_URL)
        r = requests.get(url, timeout=10)
        first_line = r.text.strip().splitlines()[0].strip().lower()
        return first_line == "on"
    except Exception as e:
        print(f"\u26a0\ufe0f [Remote Control] Failed to check status: {e}")
        return True


def is_track_liked(track_id):
    """
    Check if a track is in the user's Liked Songs.
    """
    try:
        r = spotify_get("https://api.spotify.com/v1/me/tracks/contains", params={"ids": track_id})
        if r is None or r.status_code != 200:
            print(f"\u26a0\ufe0f [Spotify] Failed to check liked status (HTTP {r.status_code}): {r.text}")
            return False

        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            return data[0]
        return False
    except Exception as e:
        print(f"\u2757 [Spotify] Error checking if track is liked: {e}")
        return False


def is_artist_never_skipped(artist_ids):
    """Check if any of the track's artists are in the never-skip list."""
    if not config.NEVER_SKIP_ARTIST_IDS_SET:
        return False
    return any(artist_id in config.NEVER_SKIP_ARTIST_IDS_SET for artist_id in artist_ids)


def get_artist_names_from_ids(artist_ids):
    """Fetch artist names from Spotify API given a list of artist IDs."""
    if not artist_ids:
        return []

    artist_names = []
    for artist_id in artist_ids:
        try:
            r = spotify_get(f"https://api.spotify.com/v1/artists/{artist_id}")
            if r.status_code == 200:
                data = r.json()
                artist_names.append(data.get("name", f"Unknown ({artist_id})"))
            else:
                artist_names.append(f"Unknown ({artist_id})")
        except Exception:
            artist_names.append(f"Unknown ({artist_id})")

    return artist_names


def get_artist_details(artist_ids):
    """Fetch full artist details (name, image, followers, genres) from Spotify API.
    Returns list of dicts matching the search_artists() result format."""
    if not artist_ids:
        return []

    results = []
    for artist_id in artist_ids:
        try:
            r = spotify_get(f"https://api.spotify.com/v1/artists/{artist_id}")
            if r and r.status_code == 200:
                data = r.json()
                images = data.get("images", [])
                results.append({
                    "id": data["id"],
                    "name": data.get("name", f"Unknown ({artist_id})"),
                    "image_url": images[0]["url"] if images else "",
                    "followers": data.get("followers", {}).get("total", 0),
                    "genres": data.get("genres", []),
                })
            else:
                results.append({"id": artist_id, "name": f"Unknown ({artist_id})",
                                "image_url": "", "followers": 0, "genres": []})
        except Exception:
            results.append({"id": artist_id, "name": f"Unknown ({artist_id})",
                            "image_url": "", "followers": 0, "genres": []})
    return results


def extract_playlist_id(text):
    """Extract a Spotify playlist ID from a URL or plain ID string."""
    import re
    text = text.strip()
    m = re.search(r'playlist[/:]([A-Za-z0-9]+)', text)
    if m:
        return m.group(1)
    if re.fullmatch(r'[A-Za-z0-9]{22}', text):
        return text
    return None


def get_playlist_name(playlist_id):
    """Fetch a playlist's name from Spotify API. Returns None on failure."""
    try:
        r = spotify_get(f"https://api.spotify.com/v1/playlists/{playlist_id}",
                        params={"fields": "name"})
        if r and r.status_code == 200:
            return r.json().get("name")
    except Exception:
        pass
    return None


def search_artists(query, limit=5, offset=0):
    """
    Search Spotify for artists by name.
    Returns list of dicts with keys: id, name, followers, genres, image_url.
    Extra fields are for display only — only id/name are stored in config.
    Supports offset for pagination.
    """
    if not query or not query.strip():
        return []

    get_spotify_token()

    try:
        r = spotify_get(
            "https://api.spotify.com/v1/search",
            params={"q": query, "type": "artist", "limit": limit, "offset": offset},
        )
        if r is None or r.status_code != 200:
            return []
        data = r.json()
        artists = data.get("artists", {}).get("items", [])
        results = []
        for a in artists:
            # Pick smallest image (usually 160px) for thumbnail use
            images = a.get("images") or []
            image_url = images[-1]["url"] if images else ""
            results.append({
                "id": a["id"],
                "name": a["name"],
                "followers": a.get("followers", {}).get("total", 0),
                "genres": a.get("genres", []),
                "image_url": image_url,
            })
        return results
    except Exception:
        return []
