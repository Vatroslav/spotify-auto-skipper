"""
Spotify API client — async version adapted from desktop app.
Uses httpx.AsyncClient, class-based token management.
"""

import asyncio
import base64
import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.database import clear_oauth_tokens, get_oauth_tokens, save_oauth_tokens, set_reauth_required

logger = logging.getLogger(__name__)


class CredentialError(Exception):
    """Raised when Spotify credentials are invalid or expired."""

    pass


class ReauthRequiredError(CredentialError):
    """Raised when the stored refresh token is dead and the user must sign in again.

    Subclass of CredentialError so existing ``except CredentialError`` handlers
    still catch it, but callers can distinguish the "send the user back through
    Spotify sign-in" case (expired/revoked refresh token) from transient or
    config credential errors (network blip, bad client secret).
    """

    pass


class SpotifyAPIError(Exception):
    """Raised when a Spotify API request fails after retries.

    Distinct from CredentialError: this covers non-auth failures (network
    exhausted, 5xx, unexpected non-200). It exists so paginating helpers can
    fail loudly instead of silently returning partial data mid-pagination —
    partial results would corrupt downstream logic (an incomplete Liked list
    poisons the Loved Sync diff; a truncated playlist scan makes Rediscovery
    treat unfetched tracks as if they don't exist).
    """

    pass


def _spotify_error(r: httpx.Response | None, context: str) -> SpotifyAPIError:
    """Build a descriptive SpotifyAPIError from a failed response (or None)."""
    if r is None:
        return SpotifyAPIError(f"{context}: network error (retries exhausted)")
    return SpotifyAPIError(f"{context}: HTTP {r.status_code}")


class SpotifyClient:
    """Async Spotify API client with token management and rate-limit retry."""

    RATE_LIMIT_MAX_RETRIES = 3
    RATE_LIMIT_RETRY_DELAYS = [5, 10, 20]

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._access_token: str | None = None
        self._token_expires_at: datetime = datetime.now(timezone.utc)
        self._http = httpx.AsyncClient(timeout=15)
        self._refresh_lock = asyncio.Lock()

    async def close(self):
        await self._http.aclose()

    # ── Authentication ───────────────────────────────────────────

    async def _load_tokens_from_db(self):
        """Load tokens from database if we don't have them in memory."""
        tokens = await get_oauth_tokens()
        if tokens:
            self._access_token = tokens["access_token"]
            if tokens["expires_at"]:
                try:
                    self._token_expires_at = datetime.fromisoformat(tokens["expires_at"])
                except (ValueError, TypeError):
                    self._token_expires_at = datetime.now(timezone.utc)

    async def refresh_access_token(self):
        """Request a new access_token using the stored refresh_token."""
        tokens = await get_oauth_tokens()
        if not tokens or not tokens.get("refresh_token"):
            raise CredentialError("No refresh token available. Please re-authorize via /auth/login.")

        refresh_token = tokens["refresh_token"]

        auth_header = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()

        try:
            r = await self._http.post(
                "https://accounts.spotify.com/api/token",
                headers={
                    "Authorization": f"Basic {auth_header}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            )
        except httpx.RequestError as e:
            raise CredentialError(f"Network error refreshing token: {e}")

        if r.status_code != 200:
            try:
                err = r.json()
                err_type = err.get("error", "")
                err_desc = err.get("error_description", "")
            except Exception:
                err_type, err_desc = "", ""

            if err_type == "invalid_client":
                raise CredentialError(f"Invalid Spotify client ID or secret. ({err_desc})")
            elif err_type == "invalid_grant":
                # Refresh token expired or revoked. Spotify expires refresh
                # tokens after six months (effective 2026-07-20). Per Spotify's
                # guidance: discard the dead token so we never retry it, flag
                # that re-auth is needed, then send the user back to sign-in.
                await clear_oauth_tokens()
                self._access_token = None
                await set_reauth_required(True)
                raise ReauthRequiredError(
                    f"Spotify refresh token expired or revoked — re-authorization required. ({err_desc})"
                )
            else:
                raise CredentialError(f"Token refresh failed (HTTP {r.status_code}): {r.text}")

        data = r.json()
        if "access_token" not in data:
            raise CredentialError(f"No access_token in response: {data}")

        self._access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))
        self._token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(0, expires_in - 100))

        # If Spotify returned a new refresh token, save it
        new_refresh = data.get("refresh_token", refresh_token)
        await save_oauth_tokens(
            self._access_token,
            new_refresh,
            self._token_expires_at.isoformat(),
        )

    async def get_token(self) -> str:
        """Returns a valid access token, refreshing if needed (lock-protected)."""
        async with self._refresh_lock:
            if self._access_token is None:
                await self._load_tokens_from_db()
            if self._access_token is None or datetime.now(timezone.utc) >= self._token_expires_at:
                await self.refresh_access_token()
            return self._access_token

    # ── HTTP wrappers with rate-limit retry ──────────────────────

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response | None:
        for attempt in range(self.RATE_LIMIT_MAX_RETRIES + 1):
            try:
                token = await self.get_token()
                headers = {"Authorization": f"Bearer {token}"}
                if method in ("PUT", "POST", "DELETE") and "json" in kwargs:
                    headers["Content-Type"] = "application/json"

                r = await self._http.request(method, url, headers=headers, **kwargs)
            except httpx.RequestError:
                if attempt < self.RATE_LIMIT_MAX_RETRIES:
                    await asyncio.sleep(self.RATE_LIMIT_RETRY_DELAYS[min(attempt, 2)])
                    continue
                return None

            if r.status_code == 401 and attempt < self.RATE_LIMIT_MAX_RETRIES:
                # Token expired/revoked mid-flight — force a real refresh
                async with self._refresh_lock:
                    await self.refresh_access_token()
                continue

            if r.status_code == 429 and attempt < self.RATE_LIMIT_MAX_RETRIES:
                delay_index = min(attempt, 2)
                try:
                    retry_after = int(r.headers.get("Retry-After", self.RATE_LIMIT_RETRY_DELAYS[delay_index]))
                except (ValueError, TypeError):
                    retry_after = self.RATE_LIMIT_RETRY_DELAYS[delay_index]
                await asyncio.sleep(max(retry_after, self.RATE_LIMIT_RETRY_DELAYS[delay_index]))
                continue

            return r

        return r

    async def _get(self, url: str, params=None) -> httpx.Response | None:
        return await self._request("GET", url, params=params)

    async def _post(self, url: str, params=None, data=None) -> httpx.Response | None:
        return await self._request("POST", url, params=params, data=data)

    async def _put(self, url: str, params=None, json=None) -> httpx.Response | None:
        return await self._request("PUT", url, params=params, json=json)

    # ── Track detection & control ────────────────────────────────

    async def get_current_track(self) -> dict | None:
        """Returns info about the currently playing song, or None."""
        r = await self._get("https://api.spotify.com/v1/me/player/currently-playing")
        if r is None or r.status_code == 204 or r.status_code != 200:
            return None

        data = r.json() or {}
        item = data.get("item")
        if not item:
            return None

        artists = item.get("artists") or []
        artist_name = artists[0]["name"] if artists else None
        artist_ids = [a["id"] for a in artists if a.get("id")]
        track_name = item.get("name")
        track_id = item.get("id")

        context = data.get("context") or {}
        context_uri = context.get("uri")

        progress_ms = data.get("progress_ms", 0)
        duration_ms = item.get("duration_ms", 0)

        album = item.get("album") or {}
        album_name = album.get("name") or ""
        album_images = album.get("images") or []
        # Pick medium-size image (300px) or fallback to first available
        album_art = ""
        for img in album_images:
            if img.get("height", 0) == 300:
                album_art = img["url"]
                break
        if not album_art and album_images:
            album_art = album_images[0]["url"]

        if track_id and artist_name and track_name:
            return {
                "id": track_id,
                "name": track_name,
                "artist": artist_name,
                "artist_ids": artist_ids,
                "album": album_name,
                "context_uri": context_uri,
                "progress_ms": progress_ms,
                "duration_ms": duration_ms,
                # Read from the same response, no extra call. The lyrics display
                # extrapolates position from progress_ms and would keep scrolling
                # through a pause without this. Absent field means playing —
                # the endpoint only answers about a track that is loaded.
                "is_playing": bool(data.get("is_playing", True)),
                "album_art": album_art,
            }
        return None

    async def skip_current_track(self):
        r = await self._post("https://api.spotify.com/v1/me/player/next")
        if r is None or r.status_code not in (200, 202, 204):
            return False
        return True

    async def previous_track(self) -> bool:
        r = await self._post("https://api.spotify.com/v1/me/player/previous")
        if r is None or r.status_code not in (200, 202, 204):
            logger.warning(
                "[Spotify] previous: playback not moved (%s)",
                "network error" if r is None else f"HTTP {r.status_code}",
            )
            return False
        return True

    async def is_spotify_paused(self) -> bool:
        r = await self._get("https://api.spotify.com/v1/me/player")
        if r is None or r.status_code != 200:
            return False
        data = r.json() or {}
        return not data.get("is_playing", True)

    async def pause_spotify_playback(self) -> bool:
        r = await self._put("https://api.spotify.com/v1/me/player/pause")
        if r is None or r.status_code not in (200, 202, 204):
            logger.warning(
                "[Spotify] pause: playback not paused (%s)",
                "network error" if r is None else f"HTTP {r.status_code}",
            )
            return False
        return True

    async def resume_spotify_playback(self) -> bool:
        r = await self._put("https://api.spotify.com/v1/me/player/play")
        if r is None or r.status_code not in (200, 202, 204):
            logger.warning(
                "[Spotify] resume: playback not resumed (%s)",
                "network error" if r is None else f"HTTP {r.status_code}",
            )
            return False
        return True

    async def restart_playlist(self, dummy_playlist_id: str) -> bool:
        """Restart the current playlist (shuffle on) to break repeating patterns.

        Bounces playback onto a dummy playlist, re-enables shuffle, then jumps
        back to the original context. Returns True only if every PUT succeeded;
        on any failure it logs a warning and returns False so the caller knows
        the restart silently degraded. The first PUT is the usual culprit — an
        invalid ``dummy_playlist_id`` (the default is a Spotify editorial
        playlist, which the API restricts for newer apps) makes it 404, and
        without this check the "restart" would look successful while doing
        nothing.
        """
        r = await self._get("https://api.spotify.com/v1/me/player/currently-playing")
        if r is None or r.status_code != 200:
            return False
        data = r.json()
        context = data.get("context", {})
        context_uri = context.get("uri")
        if not context_uri:
            return False

        def _detail(resp: httpx.Response | None) -> str:
            return "network error" if resp is None else f"HTTP {resp.status_code}"

        # Jump to the dummy playlist. If this fails, playback is untouched and
        # the rest of the dance is pointless — abort before disturbing anything.
        r = await self._put(
            "https://api.spotify.com/v1/me/player/play", json={"context_uri": f"spotify:playlist:{dummy_playlist_id}"}
        )
        if r is None or r.status_code not in (200, 202, 204):
            logger.warning(
                "[Spotify] restart_playlist: jump to dummy playlist %s failed (%s) — aborting restart",
                dummy_playlist_id,
                _detail(r),
            )
            return False
        await asyncio.sleep(1)

        # Playback is now on the dummy playlist, so we always attempt the jump
        # back even if shuffle fails — otherwise the user is stranded there.
        success = True

        r = await self._put("https://api.spotify.com/v1/me/player/shuffle", params={"state": "true"})
        if r is None or r.status_code not in (200, 202, 204):
            logger.warning("[Spotify] restart_playlist: enabling shuffle failed (%s)", _detail(r))
            success = False
        await asyncio.sleep(1)

        r = await self._put("https://api.spotify.com/v1/me/player/play", json={"context_uri": context_uri})
        if r is None or r.status_code not in (200, 202, 204):
            logger.warning("[Spotify] restart_playlist: jump back to original context failed (%s)", _detail(r))
            success = False

        return success

    async def get_all_saved_tracks(self) -> list[dict]:
        """Return all of the user's Liked Songs (paginates automatically).

        Each entry: {id, name, artist, added_at}.
        """
        results: list[dict] = []
        offset = 0
        while True:
            r = await self._get(
                "https://api.spotify.com/v1/me/tracks",
                params={"limit": 50, "offset": offset},
            )
            if r is None or r.status_code != 200:
                raise _spotify_error(r, f"Fetching Liked Songs at offset {offset}")
            data = r.json() or {}
            for entry in data.get("items") or []:
                track = entry.get("track") or {}
                if not track or not track.get("id"):
                    continue
                artists = track.get("artists") or []
                results.append(
                    {
                        "id": track["id"],
                        "name": track.get("name", ""),
                        "artist": artists[0]["name"] if artists else "Unknown",
                        "added_at": entry.get("added_at", ""),
                    }
                )
            if not data.get("next"):
                break
            offset += 50
        return results

    async def is_track_liked(self, track_id: str) -> bool:
        r = await self._get("https://api.spotify.com/v1/me/tracks/contains", params={"ids": track_id})
        if r is None or r.status_code != 200:
            return False
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            return data[0]
        return False

    async def save_track_to_liked(self, track_id: str) -> tuple[bool, str | None]:
        """Add a track to the user's Liked Songs. Returns (ok, error_message)."""
        r = await self._put("https://api.spotify.com/v1/me/tracks", params={"ids": track_id})
        if r is None:
            return False, "Network error"
        if r.status_code not in (200, 201):
            try:
                msg = (r.json().get("error") or {}).get("message", "")
            except Exception:
                msg = r.text[:200] if r.text else ""
            return False, msg or f"HTTP {r.status_code}"
        return True, None

    async def remove_track_from_liked(self, track_id: str) -> tuple[bool, str | None]:
        """Remove a track from the user's Liked Songs. Returns (ok, error_message)."""
        r = await self._request("DELETE", "https://api.spotify.com/v1/me/tracks", params={"ids": track_id})
        if r is None:
            return False, "Network error"
        if r.status_code not in (200, 201):
            try:
                msg = (r.json().get("error") or {}).get("message", "")
            except Exception:
                msg = r.text[:200] if r.text else ""
            return False, msg or f"HTTP {r.status_code}"
        return True, None

    async def get_playlist_info(self, playlist_id: str) -> dict | None:
        """Resolve a playlist ID to its info. Returns None if not found."""
        r = await self._get(
            f"https://api.spotify.com/v1/playlists/{playlist_id}",
            params={"fields": "name,description,owner(display_name)"},
        )
        if r is None or r.status_code != 200:
            return None
        data = r.json()
        return {
            "name": data.get("name", ""),
            "description": data.get("description", ""),
            "owner": (data.get("owner") or {}).get("display_name", ""),
        }

    # ── Playlist operations (Rediscovery) ────────────────────────

    async def get_user_playlists(self) -> list[dict]:
        """Return all user's playlists (paginates automatically)."""
        results = []
        offset = 0
        while True:
            r = await self._get(
                "https://api.spotify.com/v1/me/playlists",
                params={"limit": 50, "offset": offset},
            )
            if r is None or r.status_code != 200:
                raise _spotify_error(r, f"Fetching playlists at offset {offset}")
            data = r.json()
            for p in data.get("items") or []:
                if not p or not p.get("id"):
                    continue
                images = p.get("images") or []
                results.append(
                    {
                        "id": p["id"],
                        "name": p.get("name", ""),
                        "track_count": (p.get("tracks") or {}).get("total", 0),
                        "image_url": images[0]["url"] if images else "",
                    }
                )
            if not data.get("next"):
                break
            offset += 50
        return results

    async def get_playlist_tracks(self, playlist_id: str, limit: int = 100, offset: int = 0) -> dict:
        """Return a page of playlist tracks. Returns {items: [...], total: int}.

        Raises SpotifyAPIError on a failed page so callers can't mistake a
        fetch error for the end of the list (which would silently truncate a
        Rediscovery scan).
        """
        r = await self._get(
            f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
            params={
                "limit": limit,
                "offset": offset,
                "fields": "total,items(track(id,name,uri,artists(name)))",
            },
        )
        if r is None or r.status_code != 200:
            raise _spotify_error(r, f"Fetching playlist tracks at offset {offset}")
        data = r.json()
        items = []
        for entry in data.get("items") or []:
            track = entry.get("track")
            if not track or not track.get("id"):
                continue
            artists = track.get("artists") or []
            items.append(
                {
                    "id": track["id"],
                    "name": track.get("name", ""),
                    "uri": track.get("uri", ""),
                    "artist": artists[0]["name"] if artists else "Unknown",
                }
            )
        return {"items": items, "total": data.get("total", 0)}

    async def get_playlist_artist_counts(self, playlist_id: str) -> dict:
        """Return the primary artist of every track in a playlist, with track counts.

        Returns ``{"artists": {artist_id: {"name", "track_count"}}, "total_tracks",
        "tracks_without_artist"}``.

        Only the *primary* (first-credited) artist counts, so each track
        contributes exactly once and featured guests don't inflate the mix.

        Pagination is offset-driven rather than following ``next``: the ``fields``
        mask below strips ``next`` from the response, so relying on it would end
        the loop after the first page and silently truncate the scan.
        """
        artists: dict[str, dict] = {}
        total_tracks = 0
        tracks_without_artist = 0
        offset = 0
        playlist_total = 0

        while True:
            r = await self._get(
                f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
                params={
                    "limit": 100,
                    "offset": offset,
                    "fields": "total,items(track(id,artists(id,name)))",
                },
            )
            if r is None or r.status_code != 200:
                raise _spotify_error(r, f"Fetching playlist artists at offset {offset}")
            data = r.json() or {}
            playlist_total = data.get("total", 0)
            items = data.get("items") or []
            if not items:
                break

            for entry in items:
                track = (entry or {}).get("track") or {}
                total_tracks += 1
                credited = track.get("artists") or []
                primary = credited[0] if credited else {}
                artist_id = (primary or {}).get("id")
                if not artist_id:
                    # Local files and podcast episodes carry no artist ID.
                    tracks_without_artist += 1
                    continue
                slot = artists.setdefault(artist_id, {"name": primary.get("name", ""), "track_count": 0})
                slot["track_count"] += 1

            offset += len(items)
            if offset >= playlist_total:
                break

        return {
            "artists": artists,
            "total_tracks": total_tracks,
            "tracks_without_artist": tracks_without_artist,
        }

    async def get_artists_genres(self, artist_ids: list[str]) -> dict[str, list[str]]:
        """Return ``{artist_id: [genres]}`` for the given artists (batches of 50).

        An artist Spotify hasn't classified comes back with an empty list — that
        is a normal, and increasingly common, answer rather than an error.
        """
        out: dict[str, list[str]] = {}
        for i in range(0, len(artist_ids), 50):
            batch = artist_ids[i : i + 50]
            r = await self._get("https://api.spotify.com/v1/artists", params={"ids": ",".join(batch)})
            if r is None or r.status_code != 200:
                raise _spotify_error(r, f"Fetching artist genres at index {i}")
            data = r.json() or {}
            for a in data.get("artists") or []:
                # Unknown IDs come back as null entries in the array.
                if not a or not a.get("id"):
                    continue
                out[a["id"]] = a.get("genres") or []
        return out

    async def create_playlist(self, name: str, description: str = "", public: bool = False) -> dict | None:
        """Create a new playlist. Returns {id, url} or None."""
        # Need user ID first
        r = await self._get("https://api.spotify.com/v1/me")
        if r is None or r.status_code != 200:
            return None
        user_id = r.json().get("id")
        if not user_id:
            return None

        r = await self._request(
            "POST",
            f"https://api.spotify.com/v1/users/{user_id}/playlists",
            json={"name": name, "description": description, "public": public},
        )
        if r is None or r.status_code not in (200, 201):
            return None
        data = r.json()
        return {
            "id": data.get("id"),
            "url": (data.get("external_urls") or {}).get("spotify", ""),
        }

    async def add_tracks_to_playlist(self, playlist_id: str, uris: list[str]) -> bool:
        """Add tracks to playlist in batches of 100. Returns True on success."""
        for i in range(0, len(uris), 100):
            batch = uris[i : i + 100]
            r = await self._request(
                "POST",
                f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
                json={"uris": batch},
            )
            if r is None or r.status_code not in (200, 201):
                return False
        return True

    async def remove_tracks_from_playlist(self, playlist_id: str, uris: list[str]) -> tuple[bool, str | None]:
        """Remove tracks from a playlist in batches of 100.

        Returns (ok, error_message). On success, error_message is None.
        """
        for i in range(0, len(uris), 100):
            batch = uris[i : i + 100]
            r = await self._request(
                "DELETE",
                f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
                json={"tracks": [{"uri": u} for u in batch]},
            )
            if r is None:
                return False, "Network error"
            if r.status_code not in (200, 201):
                try:
                    msg = (r.json().get("error") or {}).get("message", "")
                except Exception:
                    msg = r.text[:200] if r.text else ""
                return False, msg or f"HTTP {r.status_code}"
        return True, None

    async def search_artists(self, query: str, limit: int = 5) -> list[dict]:
        if not query or not query.strip():
            return []
        r = await self._get(
            "https://api.spotify.com/v1/search",
            params={"q": query, "type": "artist", "limit": limit},
        )
        if r is None or r.status_code != 200:
            return []
        data = r.json()
        artists = data.get("artists", {}).get("items", [])
        results = []
        for a in artists:
            images = a.get("images") or []
            image_url = images[-1]["url"] if images else ""
            results.append(
                {
                    "id": a["id"],
                    "name": a["name"],
                    "followers": a.get("followers", {}).get("total", 0),
                    "genres": a.get("genres", []),
                    "image_url": image_url,
                }
            )
        return results
