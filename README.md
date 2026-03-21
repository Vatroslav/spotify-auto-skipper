# Spotify + Last.fm Auto-Skipper

Automatically skips songs on Spotify that you've already listened to recently, based on your Last.fm scrobble history. Available as a **self-hosted cloud app** (v3.0.0) or a **Windows desktop app** (v2.5.0).

---

## Cloud Version (v3.0.0)

A self-hosted web app you can run on any VPS with Docker. Access it from any device via browser — no desktop client needed.

### Screenshots

| Dashboard | Settings | Artists |
|:---:|:---:|:---:|
| ![Dashboard](screenshots/cloud/dashboard.png) | ![Settings](screenshots/cloud/settings.png) | ![Artists](screenshots/cloud/artists.png) |

| Insights | Logs |
|:---:|:---:|
| ![Insights](screenshots/cloud/insights.png) | ![Logs](screenshots/cloud/logs.png) |

### Features

- **Web dashboard** — see what's playing, skip status, and countdown to next check
- **Settings page** — configure skip window, poll interval, liked songs, restart pattern
- **Never-skip artists** — search Spotify and add artists directly from the browser
- **Insights** — daily metrics: songs played, skipped, skip rate, streaks, and more
- **Logs viewer** — filterable log browser with date navigation
- **Browser-based OAuth** — connect Spotify with one click, no manual token copying
- **Docker deployment** — single `docker compose up` with automatic HTTPS via Caddy
- **Security hardened** — CSP headers, encrypted token storage, non-root container, session auth

### Quick start

1. Clone the repo and set up environment:
   ```bash
   cd cloud
   cp .env.example .env
   # Edit .env with your Spotify, Last.fm, and secret key values
   ```

2. Start with Docker Compose:
   ```bash
   docker compose up -d
   ```

3. Visit your server URL and click **Connect Spotify** to authorize.

### Configuration

Secrets are configured via environment variables in `cloud/.env`:

| Variable | Description |
|----------|-------------|
| `SPOTIFY_CLIENT_ID` | From [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) |
| `SPOTIFY_CLIENT_SECRET` | From Spotify Developer Dashboard |
| `LASTFM_USERNAME` | Your Last.fm username |
| `LASTFM_API_KEY` | From [Last.fm API](https://www.last.fm/api/account/create) |
| `SECRET_KEY` | Session signing key (min 32 chars, generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`) |
| `BASE_URL` | Your server's public HTTPS URL |

All other settings (skip window, poll interval, etc.) are configured through the web UI and stored in SQLite.

### Health monitoring

`GET /health` returns app version and worker status. Returns HTTP 503 when the worker is dead. The Docker image includes a `HEALTHCHECK` that pings this endpoint every 30 seconds.

---

## Desktop Version (v2.5.0)

A Windows system tray app with a dark Spotify-themed GUI built with PySide6.

### Screenshots

| Settings | Never-skip Artists | Restart Pattern |
|:---:|:---:|:---:|
| ![Settings](screenshots/desktop/settings.png) | ![Never-skip Artists](screenshots/desktop/never-skip-artists.png) | ![Restart Pattern](screenshots/desktop/restart-pattern.png) |

| Remote Control | Credentials |
|:---:|:---:|
| ![Remote Control](screenshots/desktop/remote-control.png) | ![Credentials](screenshots/desktop/credentials.png) |

### Features

- **Dark Spotify-themed GUI** with setup wizard for first-run configuration
- **System tray integration** — pause skipping, check now, open settings
- **Artist search with images** — search Spotify and add to never-skip list
- **Encrypted credentials** (Fernet) — secrets never stored in plain text
- **Start with Windows** toggle
- **Always play liked songs** option
- **Playlist restart detection** — breaks repeating skip loops
- Logs all activity to daily log files with automatic purge

### Getting started

**Option 1: Pre-built EXE** — Download from the [v2.5.0 release](https://github.com/Vatroslav/spotify-auto-skipper/releases/tag/v2.5.0) and run it.

**Option 2: Run from source**
```bash
pip install -r requirements.txt
python -m spotify_auto_skipper
```

The Setup Wizard opens on first run and walks you through connecting Last.fm and Spotify.

### Configuration

Config is stored as JSON in `%APPDATA%\SpotifyAutoSkipper\`. Edit through the Settings GUI (right-click tray icon) or manually.

| Setting | Default | Description |
|---------|---------|-------------|
| `skip_window_days` | 60 | How many days back to check scrobbles |
| `poll_interval_seconds` | 120 | How often to check the current track |
| `always_play_liked_songs` | true | Never skip songs in your Liked Songs |
| `enable_restart_pattern` | true | Detect and handle playlist restart loops |
| `never_skip_artists` | [] | Artists that are never skipped |
| `start_with_windows` | false | Launch app on Windows startup |

### System tray controls

| Menu item | Description |
|-----------|-------------|
| **Pause Skipping** | Toggle skip pausing |
| **Don't skip this song** | Pause for current song only |
| **Check Now** | Immediately check current song |
| **Settings...** | Open Settings GUI |
| **Open Logs** | Open log folder |
| **Exit** | Stop the app |

---

## How it works

Both versions share the same core logic:

1. Poll Spotify API for the currently playing track
2. Look up the track on Last.fm to find when you last scrobbled it
3. If the last scrobble is within your skip window (default 60 days), skip the track
4. Optionally protect liked songs and never-skip artists from being skipped

---

## Credits

Created by [**Vatroslav Mileusnić**](https://www.linkedin.com/in/vatroslavmileusnic) with Claude Code, ChatGPT, Copilot, OpenAI Codex, Figma AI, Canvas AI
