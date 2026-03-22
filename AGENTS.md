# AGENTS.md

This file provides guidance to Codex when working with code in this repository.

## Build & Deploy

```bash
# Build and start locally
cd cloud
docker compose up -d --build

# View logs
docker compose logs -f
```

No tests or linting are configured.

## Versioning

- Version lives in `cloud/app/__init__.py` as `APP_VERSION`
- Test versions use numbered suffixes: `v3.2.0-1`, `v3.2.0-2` — never commit these to main
- **Every build must increment the test version** — if the last build was `v3.2.0-4`, the next must be `v3.2.0-5`, even for tiny changes. Never reuse a number.
- Use the exact version format the user specifies; don't invent suffixes — ask if unsure
- When releasing: set final version (remove suffix), commit, push, create git tag + GitHub release together

## Architecture

Self-hosted web app (Python/FastAPI) that auto-skips Spotify tracks based on Last.fm listening history. Deployed with Docker + Caddy.

**Runtime model:**
- **Web server** (FastAPI via Uvicorn): serves dashboard, settings, insights, logs, handles Spotify OAuth
- **Background worker** (`worker.py`): polls Spotify API, checks Last.fm scrobble history, skips tracks

**Config:** Settings in SQLite (`database.py`). Secrets encrypted with Fernet. API keys via `.env`.

## Key Modules

| Module | Role |
|--------|------|
| `cloud/app/main.py` | FastAPI app setup, lifespan, middleware |
| `cloud/app/worker.py` | Background polling loop, skip logic |
| `cloud/app/config.py` | Settings management (SQLite-backed) |
| `cloud/app/database.py` | SQLite connection, schema, migrations |
| `cloud/app/spotify_api.py` | OAuth, HTTP wrappers, track/playlist operations |
| `cloud/app/lastfm_api.py` | Scrobble history lookup |
| `cloud/app/encryption.py` | Fernet key management |
| `cloud/app/insights.py` | Log parser, metrics, records, streaks |
| `cloud/app/routers/` | FastAPI route handlers |
