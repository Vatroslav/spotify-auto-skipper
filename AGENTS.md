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

Intent-based model (migrated 2026-07-11 from the old `-N` snapshot model — no more test suffixes).

- Version lives in `cloud/app/__init__.py` as `APP_VERSION`, format `vX.Y.Z` (no suffix).
- Bump manually, in the same commit as the change: **feat** → minor, **fix / perf** → patch, **breaking** (`!:` / `BREAKING CHANGE`) → major.
- Pure docs / chore / refactor / style / test / tooling with no runtime effect → **no bump**, even when touching source.
- A conventional commit prefix is required whenever a commit touches `cloud/` — the hook `.claude/hooks/check-version-bump.sh` reads intent from it and blocks an undeclared type or a missing bump on feat/fix/perf/breaking. `.claude/hooks/check-version-decrease.sh` blocks lowering the version.
- Tag + GitHub release only when the version reaches the user (prod deploy); until then it rises without tags.

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
