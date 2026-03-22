# Spotify + Last.fm Auto-Skipper

I have a [playlist with over 5,000 songs](https://open.spotify.com/playlist/2DTe0ztu8OB5c1B80pjdfc?si=7b1c5cb732394d14), but Spotify's shuffle keeps playing the same ones over and over. This app fixes that — it checks your Last.fm scrobble history and automatically skips any song you've already heard recently, so you actually get to hear the rest of your library.

Available as a **self-hosted cloud app** (v3.2.1) or a legacy **Windows desktop app** (v2.5.0).

---

## Cloud Version (v3.2.1)

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

## Desktop Version (v2.5.0) — Legacy

> **Note:** The desktop version is no longer actively developed. The source code has been archived but the [v2.5.0 release](https://github.com/Vatroslav/spotify-auto-skipper/releases/tag/v2.5.0) remains available for download.

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

Download the pre-built EXE from the [v2.5.0 release](https://github.com/Vatroslav/spotify-auto-skipper/releases/tag/v2.5.0) and run it. The Setup Wizard opens on first run and walks you through connecting Last.fm and Spotify.

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
