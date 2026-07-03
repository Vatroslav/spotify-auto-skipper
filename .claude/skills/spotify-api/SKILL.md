---
name: spotify-api
description: Conventions for adding or changing Spotify API calls in cloud/app/spotify_api.py or call sites in the worker/routers. Use whenever writing a new Spotify endpoint call, modifying an existing one, or handling Spotify errors/pagination/rate limits. These rules exist because their violations were real production bugs (PRs #67, #69, #71, v3.13.0).
---

# Spotify API call conventions

Every rule below was learned from a shipped bug. Do not "simplify" past them.

## 1. All HTTP goes through `_request`

Use `self._get` / `self._post` / `self._put` (or `self._request` for DELETE). Never call `self._http` directly for API calls — `_request` owns token injection, 401 re-refresh, 429 Retry-After backoff, and network retries.

## 2. `_request` returns `httpx.Response | None`

`None` means the network failed after all retries. **Always check `r is None` before touching `r.status_code`.** Also guard JSON bodies: `data = r.json() or {}` (Spotify returns empty bodies on some endpoints).

## 3. Write operations must verify status — never unconditional success

Spotify player/write endpoints return 200, 202, or 204 on success. The pattern (from `skip_current_track`, `restart_playlist`):

```python
r = await self._put(url, ...)
if r is None or r.status_code not in (200, 202, 204):
    logger.warning("[Spotify] <operation>: <what failed> (%s)", "network error" if r is None else f"HTTP {r.status_code}")
    return False
return True
```

The bug this prevents: `restart_playlist` used to `return True` unconditionally; an invalid dummy playlist ID made every restart silently do nothing for months (fixed in PR #71).

Multi-step writes: if the FIRST step fails, abort before disturbing playback. If playback was already moved (e.g. onto the dummy playlist), always attempt the jump back to the original context even when an intermediate step failed — never strand the user.

Call sites in `worker.py`: surface a returned `False` into the user-facing log via `_log(...)`, don't swallow it.

## 4. Pagination: raise on failure, never return partial data

A failed page must `raise _spotify_error(r, "context at offset N")` (→ `SpotifyAPIError`). Never `break` or return what you have — a partial Liked list poisons the Loved Sync diff, and a truncated playlist scan makes Rediscovery treat unfetched tracks as never-played (both were real bugs, PR #67). Follow `get_all_saved_tracks` / `get_user_playlists` / `get_playlist_tracks` as templates.

Callers must distinguish end-of-list from error and fail cleanly: routers return 502, background jobs fail the whole job (Rediscovery already wraps Phase 1 in try/except).

## 5. Exception hierarchy — pick the right one

- `CredentialError` — bad/missing credentials or config. The worker treats this as a **clean stop** (waits for the user at `/auth/login`); the supervisor deliberately does not restart it.
- `ReauthRequiredError(CredentialError)` — dead refresh token (`invalid_grant`). Spotify expires refresh tokens after six months (effective 2026-07-20). The handler must clear stored tokens and `set_reauth_required(True)` so the token is never retried.
- `SpotifyAPIError` — non-auth failure after retries (network exhausted, 5xx, unexpected status). Raised by paginating helpers.

## 6. Poll-frequency calls get cached

The dashboard polls `GET /api/playback` every 5 s. Anything called per poll must NOT hit Spotify per tick — cache in `app_state` keyed by `track_id`, refresh only on track change, and write-through on user actions so the UI doesn't flip back to a stale value. Template: `liked_status_cache` + `_get_liked_cached` (PR #69 — before it, the liked check alone was 720 requests/hour per open tab).

The worker is a different regime: it already calls per-track (once per song), not per-poll. Keep it that way.

## 7. External gotchas

- **Editorial/Spotify-owned playlists 404 for newer apps** (API restriction since 2024). Never default to or hardcode an editorial playlist ID; expect 404 and surface it (this is the dummy-playlist trap).
- Logging: module logger (`logger = logging.getLogger(__name__)`), messages prefixed `[Spotify]`. Only WARNING+ reaches the production log — an INFO message is invisible in prod.
- Rate limits: `_request` already honors `Retry-After` with capped retries. Do not add per-call sleep loops on top.
