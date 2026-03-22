# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Permissions

- You may run all git and bash commands without asking for confirmation (commit, push, tag, release, etc.)
- Main branch has force-push protection enabled on GitHub — do not attempt `git push --force` to main

## Build & Deploy

```bash
# Build and start locally
cd cloud
docker compose up -d --build

# View logs
docker compose logs -f

# SSH deploy to VPS
ssh REDACTED_SSH "cd REDACTED_PATH/cloud && git pull && docker compose up -d --build"
```

No tests or linting are configured.

## Versioning

- Version lives in `cloud/app/__init__.py` as `APP_VERSION`
- Test versions use numbered suffixes: `v3.2.0-1`, `v3.2.0-2` — never commit these to main
- **Every build must increment the test version** — if the last build was `v3.2.0-4`, the next must be `v3.2.0-5`, even for tiny changes. Never reuse a number.
- Use the exact version format the user specifies; don't invent suffixes — ask if unsure
- When releasing: set final version (remove suffix), commit, push, create git tag + GitHub release together

## Architecture

Self-hosted web app that auto-skips Spotify tracks based on Last.fm listening history. Deployed with Docker + Caddy on a Hetzner VPS at `REDACTED_HOST`.

**Stack:** Python/FastAPI backend, Jinja2 templates, vanilla JS frontend, SQLite database, Docker deployment with Caddy reverse proxy for automatic HTTPS.

**Runtime model:**
- **Web server** (FastAPI via Uvicorn): serves dashboard, settings, insights, logs, and handles Spotify OAuth
- **Background worker** (`worker.py`): polls Spotify API, checks Last.fm scrobble history, skips tracks. Runs as an asyncio task spawned at startup.

**Config system** (`config.py`): settings stored in SQLite via `database.py`. Secrets (Spotify tokens) encrypted with Fernet (`encryption.py`). Environment variables for API keys via `.env`.

**Frontend:** Jinja2 templates (`templates/`) with vanilla CSS (`static/css/style.css`) and JS (`static/js/`). Pages: dashboard, settings, artists, insights, logs, login.

## Key Modules

| Module | Role |
|--------|------|
| `cloud/app/main.py` | FastAPI app setup, lifespan, static files, middleware |
| `cloud/app/worker.py` | Background polling loop, skip logic, adaptive polling |
| `cloud/app/config.py` | Settings management backed by SQLite |
| `cloud/app/database.py` | SQLite connection, schema, migrations |
| `cloud/app/spotify_api.py` | OAuth token refresh, HTTP wrappers, track/playlist operations |
| `cloud/app/lastfm_api.py` | Scrobble history lookup |
| `cloud/app/encryption.py` | Fernet key management for token storage |
| `cloud/app/insights.py` | Log parser, metrics, records, streaks |
| `cloud/app/state.py` | Shared application state |
| `cloud/app/routers/` | FastAPI route handlers (auth, playback, settings, artists, insights, logs) |

## Project Structure

```
cloud/
├── app/
│   ├── __init__.py          # APP_VERSION
│   ├── main.py              # FastAPI app
│   ├── worker.py            # Background skip worker
│   ├── config.py            # Settings (SQLite-backed)
│   ├── database.py          # SQLite layer
│   ├── spotify_api.py       # Spotify API client
│   ├── lastfm_api.py        # Last.fm API client
│   ├── encryption.py        # Fernet encryption
│   ├── insights.py          # Analytics engine
│   ├── state.py             # Shared state
│   ├── routers/             # API routes
│   ├── templates/           # Jinja2 HTML
│   └── static/              # CSS, JS, favicon
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Health Monitoring

`GET /health` returns app version and worker status. Returns HTTP 503 when the worker is dead. Docker HEALTHCHECK pings this every 30 seconds.
