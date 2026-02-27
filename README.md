# Spotify + Last.fm Auto-Skipper

A Windows tray app that automatically skips songs on Spotify that you've already listened to recently, based on your Last.fm scrobble history.

---

## What it does

* Checks which song is currently playing on your Spotify account
* Asks **Last.fm** when that same song was last scrobbled
* If it was played within a configurable number of days (default: 60), it automatically **skips it** on Spotify
* Runs quietly in the background with a **system tray icon**
* Logs all activity to daily log files

### v2.0 highlights

* **Setup Wizard** guides you through first-run configuration
* **Settings GUI** accessible from the tray menu (no more editing config files by hand)
* **Encrypted credentials** (Spotify secret, refresh token, Last.fm API key)
* **Start with Windows** toggle
* **Never-skip artists** with searchable names instead of raw Spotify IDs
* Config stored in `%APPDATA%\SpotifyAutoSkipper\config.json`

---

## Getting started

### First run

1. Launch the app (`.exe` or `python -m spotify_auto_skipper`)
2. The **Setup Wizard** opens automatically and walks you through:
   - **Last.fm** credentials (username + API key) with a "Test Connection" button
   - **Spotify** credentials (client ID, secret, refresh token) with a "Test Token" button
   - **Settings** (skip window, poll interval)
3. Click **Finish** and the app starts running in the tray

If you already have a config file, the wizard is skipped entirely.

### Spotify API scopes

When generating your Spotify refresh token, include these scopes:

* `user-read-currently-playing` — detect what's playing
* `user-read-playback-state` — check playback status
* `user-modify-playback-state` — skip tracks
* `user-library-read` — required if you enable "Always play liked songs"
* `user-read-private` — required for artist search in the never-skip feature

If you get `Insufficient client scope`, regenerate your refresh token with the correct scopes.

---

## Configuration

Config is stored as JSON in `%APPDATA%\SpotifyAutoSkipper\config.json`. You can edit it through the **Settings GUI** (right-click the tray icon) or manually.

See [`config-example.json`](config-example.json) for the full structure.

### Key settings

| Setting | Default | Description |
|---------|---------|-------------|
| `skip_window_days` | 60 | How many days back to check scrobbles |
| `poll_interval_seconds` | 120 | How often to check the current track (min 5s) |
| `always_play_liked_songs` | true | Never skip songs in your Liked Songs library |
| `enable_restart_pattern` | true | Detect and handle playlist restart loops |
| `never_skip_artists` | [] | List of artists (by name + ID) that are never skipped |
| `log_retention_days` | 30 | Auto-delete logs older than this |
| `start_with_windows` | false | Launch the app when Windows starts |

### Sensitive data

The fields `spotify_client_secret`, `spotify_refresh_token`, and `lastfm_api_key` are encrypted automatically using Fernet. The encryption key is stored in `%APPDATA%\SpotifyAutoSkipper\key.bin`.

### Legacy config.ini migration

If a `config.ini` file exists next to the app but no JSON config is found, the app automatically migrates it to the new format on first launch.

---

## Running the app

### Option 1: Run as Python script

```
pip install -r requirements.txt
python -m spotify_auto_skipper
```

Or via the legacy wrapper:

```
python spotify_skip_recently_played_song.py
```

### Option 2: Use the pre-built EXE

Download `SpotifyAutoSkipper.exe` from the [Releases](https://github.com/Vatroslav/spotify-auto-skipper/releases) page and run it. No installation needed.

### Option 3: Build the EXE yourself

```
pip install -r requirements.txt
pip install pyinstaller
python -m PyInstaller SpotifyAutoSkipper.spec --noconfirm
```

The output is `dist/SpotifyAutoSkipper.exe`.

---

## System tray controls

When the app is running, a green Spotify-like icon appears in your system tray. Right-click it for:

| Menu item | Description |
|-----------|-------------|
| **Pause Skipping** | Pauses all skipping (toggle to resume) |
| **Don't skip this song** | Pauses skipping for the current song only |
| **Check Now** | Immediately checks the current song |
| **Settings...** | Opens the Settings GUI |
| **Open Logs** | Opens the log folder |
| **Exit** | Stops the app |

---

## Logs

Logs are stored in a `logs` subfolder next to the app, e.g.:

```
C:\Users\<you>\Tools\spotify-auto-skipper\logs\2025-10-24.txt
```

Each line includes a timestamp. Old logs are automatically purged based on `log_retention_days` (default 30).

---

## Preventing multiple instances

The app uses a Windows mutex (`SpotifyAutoSkipperMutex`) to ensure only one instance runs at a time. If you try to start it again, it shows a popup and exits.

---

## Tech details

* **Spotify API** — current track detection, skip, playback control, artist search
* **Last.fm API** — last scrobble time lookup
* **Token refresh** — handled automatically using your permanent `refresh_token`
* **Encryption** — Fernet (from `cryptography`) for credential storage
* **Built with** — `requests`, `pystray`, `Pillow`, `cryptography`, `tkinter`

### Project structure

```
spotify_auto_skipper/
  __init__.py              # APP_VERSION
  __main__.py              # Entry point
  app.py                   # Orchestration: mutex, logging, tray, worker thread
  config.py                # JSON config, .ini migration, defaults
  encryption.py            # Fernet encrypt/decrypt for credentials
  spotify_api.py           # Spotify API wrappers
  lastfm_api.py            # Last.fm API wrapper
  tray.py                  # System tray icon and menu
  startup.py               # Windows Registry autostart
  utils.py                 # Shared helpers and state
  gui/
    __init__.py
    settings_window.py     # Settings GUI (3 tabs)
    setup_wizard.py        # First-run setup wizard
    widgets.py             # Reusable tkinter widgets
```

### Dependencies

```
requests>=2.28.0
Pillow>=9.0.0
pystray>=0.19.0
cryptography>=41.0.0
```

---

## Credits

Created by [**Vatroslav Mileusnić**](https://www.linkedin.com/in/vatroslavmileusnic)
