# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workflow

- **Questions are not instructions.** When the user asks how something works or asks a question, answer the question. Do NOT start editing code unless explicitly told to make a change.
- **DELETE safety.** Always wrap DELETE operations in a transaction: BEGIN, DELETE, check affected row count matches expected, COMMIT only if correct, ROLLBACK otherwise.

## Permissions

- Main branch has force-push protection enabled on GitHub — do not attempt `git push --force` to main

## Build & Deploy

```bash
# Build and start locally
cd cloud
docker compose up -d --build

# View logs
docker compose logs -f
```

No tests or linting are configured. For deployment, use the `/deploy` skill which reads connection details from the user's private config.

## Versioning

- Version lives in `cloud/app/__init__.py` as `APP_VERSION`
- Test versions use numbered suffixes: `v3.2.0-1`, `v3.2.0-2` — never commit these to main
- **Every build must increment the test version** — if the last build was `v3.2.0-4`, the next must be `v3.2.0-5`, even for tiny changes. Never reuse a number.
- Use the exact version format the user specifies; don't invent suffixes — ask if unsure
- When releasing: set final version (remove suffix), commit, push, create git tag + GitHub release together

## Architecture

Self-hosted web app that auto-skips Spotify tracks based on Last.fm listening history. Deployed with Docker + Caddy on a VPS.

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

### Worker self-healing

The background worker can die two ways, and they are handled differently on purpose:

- **Crash** (unexpected exception escapes the loop, or fails in pre-loop setup): an in-process supervisor (`worker.py::worker_supervisor`, spawned in the lifespan) detects the dead task and restarts it via `restart_worker_if_dead()`, with an exponential backoff cap so a recurring crash doesn't spam logs. Recovery is in seconds, no container bounce.
- **Clean stop** (re-auth / credential needed): the worker returns cleanly and the supervisor leaves it alone — restarting would just re-hit the dead token and loop. This state waits for the user to reconnect at `/auth/login`, which restarts the worker itself. The supervisor distinguishes the two via `task.exception()` (a crash has one; a clean return does not).

**Conscious decision — no container-level autoheal.** `restart: unless-stopped` only reacts to the process exiting, not to an unhealthy status, so a fully wedged process (blocked event loop, dead uvicorn) is NOT auto-recovered — the supervisor runs on the same loop and can't fix that. We deliberately do not add a container autoheal (e.g. willfarrell/autoheal) or an app self-exit: the historical worker deaths have all been either crashes (now self-healed in-process) or re-auth (needs a human anyway), and a naive autoheal would restart-loop the container on the re-auth 503. That tail risk is left as **signal-only**: the Docker HEALTHCHECK still flips the container to unhealthy so it's visible in `docker ps` / the health JSON. Revisit only if a real wedged-process incident occurs.
