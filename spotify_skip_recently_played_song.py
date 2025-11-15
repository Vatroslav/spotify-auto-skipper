# -------------------------------------------------------------
# Spotify + Last.fm AUTO-SKIPPER (with detailed comments)
# -------------------------------------------------------------
# Author: Vatroslav + ChatGPT 5
#
# What it does:
# - regularly checks which song is currently playing on your Spotify account
# - asks Last.fm when that same song was last scrobbled
# - if it was scrobbled within the last 30 days, it automatically skips it on Spotify
#
# Why Last.fm? Because you’re already scrobbling everything there and it holds your centralized history.
# Why Spotify API? Because it’s the only one allowed to send a “skip” command for your account.
#
# What you need to enter:
# - LASTFM_USER and LASTFM_API_KEY
# - CLIENT_ID, CLIENT_SECRET, and REFRESH_TOKEN from your Spotify app
#
# How token refreshing works:
# - Spotify’s access_token is valid for about ~1h; REFRESH_TOKEN is “permanent”
# - before every Spotify call, the script checks if the token has expired
# and, if so, automatically requests a new access_token (without your intervention)
#
# Note:
# - The script is written to be understandable even without Python knowledge:
# just read the comments above each function and code block.
# -------------------------------------------------------------


import time # for pauses between checks
import base64 # for Base64 encoding of ClientID:ClientSecret
from datetime import datetime, timedelta, timezone # working with time
import requests # HTTP calls to APIs (Spotify, Last.fm)

import ctypes # ctypes needed to prevent multiple instances of the same app from running

import sys # sys and os needed for logging
import os

import configparser # configparser needed to read config.ini

from PIL import Image, ImageDraw, ImageFont # PIL, pystray, and threading needed for displaying in the system tray
import pystray
import threading

import builtins # builtins needed to print timestamps with every print

APP_VERSION = "v1.4.0"

# -------------------------------------------------------------
# SETTINGS FROM config.ini
# -------------------------------------------------------------

# The script is run via an EXE
# To create a new EXE, run: pyinstaller --noconsole --onefile spotify_skip_recently_played_song.py


# Load configuration from config.ini
config = configparser.ConfigParser()
config.read(os.path.join(os.path.dirname(getattr(sys, "executable", sys.argv[0])), "config.ini"))

# Last.fm
LASTFM_API_KEY = config.get("LastFM", "api_key")
LASTFM_USER = config.get("LastFM", "username")

# Spotify
CLIENT_ID = config.get("Spotify", "client_id")
CLIENT_SECRET = config.get("Spotify", "client_secret")
REFRESH_TOKEN = config.get("Spotify", "refresh_token")

# Settings
SKIP_WINDOW_DAYS = config.getint("Settings", "skip_window_days", fallback=60)
POLL_INTERVAL_SECONDS = config.getint("Settings", "poll_interval_seconds", fallback=120)
ENABLE_RESTART_PATTERN = config.getboolean("Settings", "enable_restart_pattern", fallback=True)
RESTART_PATTERN_SONG_COUNT = config.getint("Settings", "restart_pattern_song_count", fallback=5)
RESTART_PATTERN_DAY_DIFF = config.getint("Settings", "restart_pattern_day_diff", fallback=2)
DUMMY_PLAYLIST_ID = config.get("Settings", "dummy_playlist_id", fallback="37i9dQZF1DX0XUsuxWHRQd")
REMOTE_CONTROL_URL = config.get("Settings", "remote_control_url", fallback="ON")

# Simple “soft” timeout cache for access_token
SPOTIFY_TOKEN = None
TOKEN_EXPIRES_AT = datetime.now(timezone.utc) # the moment when the token (approximately) expires

# -------------------------------------------------------------
# PREVENTING MULTIPLE INSTANCES (Windows mutex)
# -------------------------------------------------------------
# This code uses the Windows API to ensure the application runs
# only once at a time. If another instance of the .exe is started,
# Windows returns the code "ERROR_ALREADY_EXISTS" (183),
# after which the script displays a notification and exits immediately.
# -------------------------------------------------------------

# Create a unique global "mutex" — you can change the name if you want
mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "SpotifyAutoSkipperMutex")

# Check the last error from the Windows API
last_error = ctypes.windll.kernel32.GetLastError()

# If a mutex with the same name already exists, it means the application is already running
if last_error == 183:  # ERROR_ALREADY_EXISTS
    # Display a simple message to the user (you can remove it if you want silent operation)
    ctypes.windll.user32.MessageBoxW(
        0,
        "Spotify Auto-Skipper is already running and running in the background.",
        "Already started",
        0x40  # MB_ICONINFORMATION
    )
    sys.exit(0)
    
# -------------------------------------------------------------
# LOGGING TO A FILE
# -------------------------------------------------------------
# This block redirects all printed messages (print) and errors (stderr)
# to a daily log file. It automatically creates a new file every day in the "logs" subfolder.
# Example: C:\Users\mileu\Dropbox\Tools\Spotify skip recently scrobbled song\logs\2025-10-24.txt
# -------------------------------------------------------------

# Specify the folder where the logs will be stored
LOG_DIR = os.path.join(os.path.dirname(getattr(sys, "executable", sys.argv[0])), "logs")

# If the folder doesn't exist, create it
os.makedirs(LOG_DIR, exist_ok=True)

# Make the name of the log file according to today's date
log_filename = datetime.now().strftime("%Y-%m-%d") + ".txt"
log_path = os.path.join(LOG_DIR, log_filename)

# Open the file in "append" mode (continues writing, does not delete old logs)
log_file = open(log_path, "a", encoding="utf-8")

# Redirect standard output (print) and errors (traceback, warnings) to a log file
sys.stdout = log_file
sys.stderr = log_file

# Each print() will immediately write the line to the file (no buffering)
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Write the header at the beginning of each run
print(f"\n{'='*60}")
print(f"🕒 Starting the app ({APP_VERSION}): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"{'='*60}\n")
log_file.flush()

# -------------------------------------------------------------
# FUNCTION FOR AUTOMATIC TIMESTAMP ON EVERY PRINT
# -------------------------------------------------------------
_original_print = print # save the original print function

def print(*args, **kwargs):
    """
    Prints each message to the log with the current time (HH:MM:SS) in front. 
    If a line contains a 🎵, it adds a blank line before it for clarity.
    """
    time_prefix = datetime.now().strftime("[%H:%M:%S]")
    text = " ".join(str(a) for a in args)
    if "🎵" in text:
        _original_print("")  # add a blank line before the song
    _original_print(time_prefix, text, **kwargs)
    log_file.flush()

# -------------------------------------------------------------
# SYSTEM TRAY ICON
# -------------------------------------------------------------
# This part creates a small icon next to the clock (system tray)
# and displays a tooltip with the application name.
# When you right-click and select "Exit", the application closes gracefully.
# -------------------------------------------------------------

should_exit = threading.Event()
skipping_paused = False
temp_pause_track_id = None  # Track ID for which skipping is temporarily paused

def create_tray_icon():
    """
    Creates a tray icon (next to the clock) that looks like the Spotify logo: 
    - Green Background (#1DB954) 
    - Three white curved Spotify lines 
    - Black skip symbol (▶▶│) over them 
    Right click -> 'Open Logs' opens the log folder, 'Exit' closes the application.
    """
    
    global skipping_paused, temp_pause_track_id

    # ---------------------------------------------------------
    # CREATE ICON (size 64x64 because tray automatically scales)
    # ---------------------------------------------------------
    size = 64
    img = Image.new("RGB", (size, size), color=(29, 185, 84))  # Spotify green (#1DB954)
    draw = ImageDraw.Draw(img)

    # Draw three white curved lines (Spotify "waves")
    wave_color = (255, 255, 255)
    for i, offset in enumerate([10, 20, 30]):
        draw.arc([10, offset, 54, offset + 25], start=200, end=340, fill=wave_color, width=4)

    # Add black skip symbol (▶▶│)
    skip_color = (0, 0, 0)
    draw.polygon([(36, 20), (46, 32), (36, 44)], fill=skip_color) # first triangle
    draw.polygon([(46, 20), (56, 32), (46, 44)], fill=skip_color) # second triangle
    draw.rectangle([57, 20, 59, 44], fill=skip_color)              # line (│)

    # ---------------------------------------------------------
    # MENU ACTIONS
    # ---------------------------------------------------------
    def toggle_skip(icon, item):
        global skipping_paused
        skipping_paused = not skipping_paused
        state = "paused" if skipping_paused else "resumed"
        print(f"⏯️ Skipping manually {state} from tray.")
        # Update menu label dynamically
        icon.update_menu()

    def pause_current_song(icon, item):
        global temp_pause_track_id
        try:
            track = get_current_track()
            if track and track.get('id'):
                temp_pause_track_id = track['id']
                print(f"🎵 Temporarily paused skipping for: {track['artist']} – {track['name']}")
                print(f"   (Will resume skipping when next song plays)")
            else:
                print("⚠️ No song currently playing to pause skipping for.")
        except Exception as e:
            print(f"❗ Failed to pause current song: {e}")
        icon.update_menu()

    def open_logs(icon, item):
        logs_path = os.path.join(os.path.dirname(getattr(sys, "executable", sys.argv[0])), "logs")
        os.startfile(logs_path)
    
    def on_exit(icon, item):
        print("🛑 Exit clicked from tray.")
        icon.stop()
        log_file.flush()
        os._exit(0)
        
    def skip_label(item):
        return "⏸️ Resume Skipping" if skipping_paused else "⏯️ Pause Skipping"

    # Menu definition ("lambda" used to show dynamic text)
    menu = pystray.Menu(
        pystray.MenuItem(skip_label, toggle_skip),
        pystray.MenuItem("🎵 Don't skip this song", pause_current_song),
        pystray.MenuItem("📁 Open Logs", open_logs),
        pystray.MenuItem("❌ Exit", on_exit)
    )

    # ---------------------------------------------------------
    # CREATE A TRAY ICON AND RUN IT IN THE BACKGROUND
    # ---------------------------------------------------------
    icon = pystray.Icon("spotify_skipper", img, f"Spotify Auto-Skipper {APP_VERSION}", menu)
    threading.Thread(target=icon.run, daemon=False).start()

# -------------------------------------------------------------
# TRACKING THE LAST CHECKED SONG
# -------------------------------------------------------------
# We remember these variables to avoid checking the same song multiple times
# (e.g. if the script enters a loop while the song is still playing).
# -------------------------------------------------------------
last_checked_track_id = None
last_checked_timestamp = None

# -------------------------------------------------------------
# AUXILIARY FUNCTIONS FOR SPOTIFY AUTHENTICATION AND CALLS
# -------------------------------------------------------------

def refresh_access_token():
    """
    Request a new 'access_token' from Spotify using 'refresh_token'.
    This works "in the background" so you don't have to log in again every hour.

    Technically:
    - Spotify expects a Basic auth header with Base64(ClientID:ClientSecret).
    - 'grant_type' must be 'refresh_token'.
    - If successful, we will get a new 'access_token' (and possibly a new 'refresh_token', but most often not).
    - 'expires_in' is about 3600s (1h) — we "cut" it to ~3500s to refresh a little earlier.
    """
    global SPOTIFY_TOKEN, TOKEN_EXPIRES_AT

    # ClientID:ClientSecret in Base64, as Spotify asks for in the header
    auth_header = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

    # POST to the Spotify token endpoint
    r = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": REFRESH_TOKEN,
        },
        timeout=15,
    )

    # If something goes wrong (e.g. wrong credentials, expired refresh token...), raise a clear error
    if r.status_code != 200:
        raise RuntimeError(f"Failed to refresh token (HTTP {r.status_code}): {r.text}")

    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"No access_token in response: {data}")

    SPOTIFY_TOKEN = data["access_token"]

    # If the API returns 'expires_in', use it; otherwise assume ~3600s.
    expires_in = int(data.get("expires_in", 3600))
    # Refresh 100 seconds early to avoid 'on the verge' of expiration during the call
    TOKEN_EXPIRES_AT = datetime.now(timezone.utc) + timedelta(seconds=max(0, expires_in - 100))

    print("🔄 [Spotify] Access token refreshed.")


def get_spotify_token():
    """
    Returns a valid Spotify access_token.
    - If we don't have one or it has expired -> automatically refresh it.
    - Call this from every function that goes to the Spotify API (e.g. get_current_track, skip_current_track).
    """
    global SPOTIFY_TOKEN
    if SPOTIFY_TOKEN is None or datetime.now(timezone.utc) >= TOKEN_EXPIRES_AT:
        refresh_access_token()
    return SPOTIFY_TOKEN


def spotify_get(url, params=None):
    """
    Streamlining GET calls to the Spotify API. 
    - Always adds a valid Authorization header with a Bearer token. 
    - Return a 'requests.Response' object so we can check the status and content. 
    - It has a basic timeout so that the script does not "hang" indefinitely.
    """
    token = get_spotify_token()
    return requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        timeout=15,
    )


def spotify_post(url, params=None, data=None):
    """
    Streamlining POST calls to the Spotify API. 
    - Use a valid token. 
    - We don't need 'data' for the skip command, only header and endpoint.
    """
    token = get_spotify_token()
    return requests.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        data=data or {},
        timeout=15,
    )

def spotify_put(url, params=None, data=None):
    """Wrapper for PUT calls to Spotify API (for playback/shuffle control)."""
    token = get_spotify_token()
    return requests.put(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        params=params or {},
        json=data or {},
        timeout=15,
    )

# -------------------------------------------------------------
# FUNCTIONS FOR GETTING THE CURRENT SONG AND SKIP
# -------------------------------------------------------------

def get_current_track():
    """
    Returns a dict with information about the currently playing song.
    Example:
    {
        "id": "6HD0bX8N8Yd7Ij3mAjI93y",
        "name": "Heart of the Forest",
        "artist": "Skyforest"
    }
    If nothing is playing -> returns None.
    """

    r = spotify_get("https://api.spotify.com/v1/me/player/currently-playing")

    # 204 = nothing is playing, 200 = there is content
    if r.status_code == 204:
        return None
    if r.status_code != 200:
        print(f"⚠️ [Spotify] Unexpected status {r.status_code}: {r.text}")
        return None

    data = r.json() or {}
    item = data.get("item")
    if not item:
        return None

    # Extract basic data
    artists = item.get("artists") or []
    artist_name = artists[0]["name"] if artists else None
    track_name = item.get("name")
    track_id = item.get("id")

    if track_id and artist_name and track_name:
        return {"id": track_id, "name": track_name, "artist": artist_name}

    return None


def skip_current_track():
    """
    Sends a command to Spotify to skip to the next song.
    Endpoint: POST /v1/me/player/next
    Assumption: you have an active device (desktop app, mobile, web player).
    """
    r = spotify_post("https://api.spotify.com/v1/me/player/next")
    if r.status_code not in (200, 202, 204):
        # 204 is a common success; 202 sometimes means "accepted"; 200 is returned by the web player
        print(f"⚠️ [Spotify] Skip failed (HTTP {r.status_code}): {r.text}")
        
def is_spotify_paused():
    r = spotify_get("https://api.spotify.com/v1/me/player")
    if r.status_code != 200:
        return False
    data = r.json() or {}
    return not data.get("is_playing", True)
    
def pause_spotify_playback():
    r = requests.put(
        "https://api.spotify.com/v1/me/player/pause",
        headers={"Authorization": f"Bearer {get_spotify_token()}"},
        timeout=10,
    )
    if r.status_code not in (200, 202, 204):
        print(f"⚠️ [Spotify] Failed to pause after skip (HTTP {r.status_code}): {r.text}")

def restart_playlist():
    """Restart the current playlist (shuffle on) to break repeating patterns."""
    try:
        # Get current context (playlist URI)
        r = spotify_get("https://api.spotify.com/v1/me/player/currently-playing")
        if r.status_code != 200:
            print(f"⚠️ [Spotify] Cannot get current playback context (HTTP {r.status_code})")
            return
        data = r.json()
        context = data.get("context", {})
        context_uri = context.get("uri")
        if not context_uri:
            print("⚠️ [Spotify] No playlist context found — cannot restart.")
            return

        print(f"🔁 Restarting playlist: {context_uri}")
        # Start a dummy playlist first (can be any known Spotify playlist)
        spotify_put("https://api.spotify.com/v1/me/player/play",
            data={"context_uri": f"spotify:playlist:{DUMMY_PLAYLIST_ID}"}) # “dummy” playlist
        time.sleep(1)

        # Enable shuffle again
        spotify_put("https://api.spotify.com/v1/me/player/shuffle", params={"state": "true"})
        time.sleep(1)

        # Restart original playlist
        spotify_put("https://api.spotify.com/v1/me/player/play", data={"context_uri": context_uri})
        print("✅ Playlist restarted successfully.")
    except Exception as e:
        print(f"❗ Failed to restart playlist: {e}")
        
def is_skipping_enabled():
    """Checks the Dropbox remote_control.txt file; returns True if ON."""
    if not REMOTE_CONTROL_URL:
        print("⚠️ [Remote Control] No REMOTE_CONTROL_URL set.")
        return True
    try:
        r = requests.get(REMOTE_CONTROL_URL, timeout=10)
        first_line = r.text.strip().splitlines()[0].strip().lower()
        return first_line == "on"
    except Exception as e:
        print(f"⚠️ [Remote Control] Failed to check status: {e}")
        return True

# -------------------------------------------------------------
# LAST.FM: CHECK WHEN A SONG WAS LAST SCROBBLED
# -------------------------------------------------------------

def get_last_play_date(artist, track):
    """
    Returns the datetime (UTC) of the last scrobble for the given (artist, track)
        from Last.fm, or None if there are no scrobbles.
    Endpoint: user.getTrackScrobbles
    - Here we use 'params' instead of manually building the URL format-string, so that the artist/song names
        are correctly URL-encoded (important for diacritics, commas, brackets…).
    - 'limit=1' only searches for the latest scrobbles -> fastest and sufficient for our logic.
    """
    try:
        r = requests.get(
            "https://ws.audioscrobbler.com/2.0/",
            params={
                "method": "user.gettrackscrobbles",
                "user": LASTFM_USER,
                "artist": artist,
                "track": track,
                "api_key": LASTFM_API_KEY,
                "format": "json",
                "limit": 1,
            },
            timeout=15,
        )
    except requests.RequestException as e:
        print(f"⚠️ [Last.fm] Network error: {e}")
        return None

    if r.status_code != 200:
        print(f"⚠️ [Last.fm] Unexpected status {r.status_code}: {r.text}")
        return None

    data = r.json() or {}
    trackscrobbles = data.get("trackscrobbles", {})
    scrobbles = trackscrobbles.get("track")

    # If there are no scrobbles for that song, the API may return an empty object/list.
    if not scrobbles:
        return None

    # If it's a list, take the first (latest) one and extract the timestamp
    if isinstance(scrobbles, list):
        latest = scrobbles[0]
        date_obj = latest.get("date", {})
        uts = date_obj.get("uts")
        if uts:
            try:
                return datetime.fromtimestamp(int(uts), tz=timezone.utc)
            except ValueError:
                return None

    # If it's a single object (less common), try the same
    if isinstance(scrobbles, dict):
        date_obj = scrobbles.get("date", {})
        uts = date_obj.get("uts")
        if uts:
            try:
                return datetime.utcfromtimestamp(int(uts))
            except ValueError:
                return None

    return None

# -------------------------------------------------------------
# MAIN LOOP: "CHECK → DECIDE → (MAYBE) SKIP" LOGIC
# -------------------------------------------------------------

def main_loop():
    """
    A loop that:
    - checks what's playing every POLL_INTERVAL_SECONDS seconds
    - if something is playing, asks Last.fm when it was last played
    - if it's within SKIP_WINDOW_DAYS days, sends a skip
    - otherwise does nothing and just waits for the next check
    """
    global last_checked_track_id, last_checked_timestamp, temp_pause_track_id
    
    recent_skip_days = []

    print("🚀 Auto-skipper enabled. Skipping songs that have been listened to in the last "
          f"{SKIP_WINDOW_DAYS} days.\n")

    while True:
        try:
            # Manual pause from the tray
            if skipping_paused:
                print("⏸️ Skipping manually paused via tray.")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            # Remote Dropbox toggle
            if not is_skipping_enabled():
                print("🚫 Remote control: skipping temporarily disabled.")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            
            track = get_current_track()

            # If nothing plays or there is no valid data — skip
            if not track or not track.get('artist') or not track.get('id'):
                print("🎧 Nothing is playing right now.")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            # If nothing is playing at the moment (pause, stop, silence) – just take a nap and continue
            if not track['artist'] or not track['id']:
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            # Skip if it's the same song as last time
            if track['id'] == last_checked_track_id:
                print(f"⏸️ Same song as last time ({track['name']}) — skipping the check.")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            # If it's a new song, remember the ID
            last_checked_track_id = track['id']
            last_checked_timestamp = datetime.now(timezone.utc)
            
            # Clear temporary pause if a different song is playing
            if temp_pause_track_id and temp_pause_track_id != track['id']:
                print(f"🔓 Clearing temporary pause (song changed)")
                temp_pause_track_id = None

            print(f"🎵 Currently playing: {track['artist']} – {track['name']}")
            
            # Check if skipping is temporarily paused for this specific song
            if temp_pause_track_id == track['id']:
                print(f"⏸️ Skipping is temporarily paused for this song")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            # Get the latest scrobble date from Last.fm
            last_played = get_last_play_date(track['artist'], track['name'])
            if last_played:
                # Calculate how many days have passed since the last scrobble
                days_since = (datetime.now(timezone.utc) - last_played).days
                # Print information about it
                print(f"ℹ️ Last scrobble: {last_played.strftime('%Y-%m-%d')} - {days_since} days ago")

                # If it's within our 'window' (e.g. 30 days), skip it
                cutoff = datetime.now(timezone.utc) - timedelta(days=SKIP_WINDOW_DAYS)
                if last_played > cutoff:
                    print(f"⏭️ Already listened to {days_since} days ago — skipping")
                    was_paused = is_spotify_paused()
                    skip_current_track()
                    if was_paused:
                        time.sleep(1)  # give Spotify a moment to switch tracks
                        pause_spotify_playback()
                        
                    # Track recent skip patterns (only if enabled)
                    if ENABLE_RESTART_PATTERN:
                        recent_skip_days.append(days_since)
                        if len(recent_skip_days) > RESTART_PATTERN_SONG_COUNT:
                            recent_skip_days.pop(0)

                        # Detect repeating pattern within configured tolerance
                        if (
                            len(recent_skip_days) == RESTART_PATTERN_SONG_COUNT
                            and max(recent_skip_days) - min(recent_skip_days) <= RESTART_PATTERN_DAY_DIFF
                        ):
                            print(f"⚠️ Detected repeating pattern ({RESTART_PATTERN_SONG_COUNT} skips within ±{RESTART_PATTERN_DAY_DIFF} day) — restarting playlist...")
                            restart_playlist()
                            recent_skip_days.clear()
                        
                    time.sleep(5)
                    # Immediately check the next song instead of waiting full interval
                    print("🔁 Checking the next song right away...")
                    continue
                else:
                    print("✅ The last scrobble is older than the window — not skipping.")
            else:
                print("ℹ️ There's no scrobble for this song — not skipping.")


        except KeyboardInterrupt:
            # Provides a graceful exit if you manually terminate the script
            print("\n👋 Stopped by user.")
            break
        except Exception as e:
            # Any unexpected error: print and continue after a short sleep
            print(f"❗ Unexpected error: {e}")
            time.sleep(POLL_INTERVAL_SECONDS)

        # Standard pause between check cycles
        time.sleep(POLL_INTERVAL_SECONDS)

# -------------------------------------------------------------
# Entry point: start the main loop
# -------------------------------------------------------------

if __name__ == "__main__":
    create_tray_icon()
    main_loop()
