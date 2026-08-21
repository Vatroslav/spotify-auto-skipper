"""
LRCLIB lyrics lookup — time-synced lyrics for the car display.

LRCLIB is free, keyless and community-run. It has no notion of Spotify ids, so
a track is identified by (artist, title, album, duration). That is the weak
point of the whole feature: a near-miss returns someone else's timings, which
looks worse on a car screen than no lyrics at all. Hence the duration guard on
every result — see _duration_matches.
"""

import logging
import re

import httpx

from app import APP_VERSION

logger = logging.getLogger(__name__)

LRCLIB_BASE = "https://lrclib.net/api"

# LRCLIB asks clients to identify themselves rather than pose as a browser.
USER_AGENT = f"SpotifyAutoSkipper/{APP_VERSION} (https://github.com/Vatroslav/spotify-auto-skipper)"

_TIMEOUT = 10.0

# How far a candidate's duration may sit from Spotify's before we refuse it.
# /api/get is already tolerant server-side (it matched a 239s track on a 238s
# query), so this only really guards the /api/search fallback, where the first
# result is often a compilation cut with different timings.
_DURATION_TOLERANCE_S = 3.0

# [mm:ss.xx] or [mm:ss.xxx], possibly several on one line for a repeated refrain.
_LRC_TAG = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")


class LyricsResult:
    """One resolved lyrics lookup.

    `lines` is empty for an instrumental or for plain-only lyrics — the car
    display needs timings, and unsynced text cannot be scrolled automatically.
    """

    def __init__(
        self,
        *,
        synced: str = "",
        plain: str = "",
        instrumental: bool = False,
    ):
        self.synced = synced
        self.plain = plain
        self.instrumental = instrumental

    @property
    def has_synced(self) -> bool:
        return bool(self.synced.strip())


def parse_lrc(synced: str) -> list[dict]:
    """Parse LRC text into [{"t": milliseconds, "text": str}], sorted by time.

    Blank lines are kept: a timestamped empty line marks an instrumental gap,
    and the display renders it rather than jumping ahead to the next verse.
    Lines without a timestamp (LRC metadata like [ar:...]) are dropped.
    """
    out: list[dict] = []
    for raw_line in synced.splitlines():
        tags = list(_LRC_TAG.finditer(raw_line))
        if not tags:
            continue
        text = raw_line[tags[-1].end() :].strip()
        for tag in tags:
            minutes, seconds, fraction = tag.group(1), tag.group(2), tag.group(3) or "0"
            # LRC fractions are hundredths by convention but thousandths appear
            # in the wild; pad so "5" reads as 500ms, not 5ms.
            millis = int(fraction.ljust(3, "0")[:3])
            out.append({"t": int(minutes) * 60_000 + int(seconds) * 1_000 + millis, "text": text})
    out.sort(key=lambda line: line["t"])
    return out


def _duration_matches(candidate_seconds: float | None, expected_seconds: float | None) -> bool:
    """True when a candidate's length is close enough to be the same recording."""
    if not expected_seconds or not candidate_seconds:
        return True  # nothing to compare against — accept and let the guard fall to /api/get
    return abs(float(candidate_seconds) - float(expected_seconds)) <= _DURATION_TOLERANCE_S


def _result_from_payload(payload: dict) -> LyricsResult:
    return LyricsResult(
        synced=payload.get("syncedLyrics") or "",
        plain=payload.get("plainLyrics") or "",
        instrumental=bool(payload.get("instrumental")),
    )


async def fetch_lyrics(
    artist: str,
    track: str,
    album: str = "",
    duration_ms: int = 0,
) -> LyricsResult | None:
    """Look up lyrics for one track. None means LRCLIB has nothing for it.

    Two attempts: the exact-match endpoint first, then a search fallback for
    when Spotify's album name differs from whatever the LRC was filed under
    (remasters, deluxe editions, regional releases). Search results are
    duration-filtered — an unfiltered first hit is frequently the wrong cut.

    A network failure raises nothing and returns None: the caller treats a
    missing lookup the same as a missing song, and the cache is not poisoned
    because only the router decides what to store.
    """
    duration_s = (duration_ms / 1000) if duration_ms else 0.0
    headers = {"User-Agent": USER_AGENT}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=headers) as client:
            params = {"artist_name": artist, "track_name": track}
            if album:
                params["album_name"] = album
            if duration_s:
                params["duration"] = int(round(duration_s))

            r = await client.get(f"{LRCLIB_BASE}/get", params=params)
            if r.status_code == 200:
                return _result_from_payload(r.json() or {})
            if r.status_code != 404:
                logger.warning("[LRCLIB] get returned HTTP %s for %s - %s", r.status_code, artist, track)
                return None

            # 404 — fall back to search without the album constraint.
            r = await client.get(
                f"{LRCLIB_BASE}/search",
                params={"artist_name": artist, "track_name": track},
            )
            if r.status_code != 200:
                return None

            candidates = r.json() or []
            if not isinstance(candidates, list):
                return None

            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                if not _duration_matches(candidate.get("duration"), duration_s):
                    continue
                result = _result_from_payload(candidate)
                if result.has_synced or result.instrumental:
                    return result
            return None

    except httpx.HTTPError as e:
        logger.warning("[LRCLIB] lookup failed for %s - %s: %s", artist, track, e)
        return None
    except ValueError as e:
        # Malformed JSON from an otherwise-200 response.
        logger.warning("[LRCLIB] unreadable response for %s - %s: %s", artist, track, e)
        return None
