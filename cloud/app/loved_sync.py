"""
Loved Sync — diff Spotify Liked Songs against Last.fm Loved Tracks.

Matching mirrors the worker's skip-check logic: each Spotify track is keyed by
(artist, alias_or_track_name) where the alias comes from the track_aliases
table (manual user-defined corrections). The same key is used to look up the
Last.fm Loved set.
"""

import re
from difflib import SequenceMatcher

from app.database import get_all_track_aliases, get_loved_sync_ignored
from app.lastfm_api import LASTFM_ERROR, get_loved_tracks
from app.spotify_api import CredentialError, SpotifyAPIError


def _norm_key(artist: str, name: str) -> tuple[str, str]:
    return (artist.strip().lower(), name.strip().lower())


_PAREN_RE = re.compile(r"[\(\[].*?[\)\]]")
_SUFFIX_RE = re.compile(
    r"\s*-\s*(remaster(ed)?|remix|version|edit|mix|anniversary|single|live|demo|instrumental).*",
    re.I,
)
_FEAT_RE = re.compile(r"\s+(feat\.?|ft\.?)\s+.*", re.I)
_PUNCT_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")


def _normalize(s: str) -> str:
    """Aggressive normalization for fuzzy matching only.

    Used to score similarity — never as a match key. The actual alias still
    stores the user-confirmed Last.fm name verbatim.
    """
    if not s:
        return ""
    s = s.lower().replace("&", "and")
    s = s.replace("`", "'").replace("´", "'").replace("’", "'").replace("‘", "'")
    s = _PAREN_RE.sub("", s)
    s = _SUFFIX_RE.sub("", s)
    s = _FEAT_RE.sub("", s)
    s = _PUNCT_RE.sub(" ", s)
    s = _SPACE_RE.sub(" ", s).strip()
    return s


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def find_candidates(spotify_track: dict, lastfm_pool: list[dict], top_n: int = 5) -> list[dict]:
    """For one Spotify track, return up to top_n likely Last.fm matches.

    Filters by normalized-artist similarity (>= 0.85) so cross-artist
    suggestions are excluded. Track name similarity is weighted heavier in
    the final score; entries below 0.5 name-similarity are dropped.
    """
    sp_artist = _normalize(spotify_track["artist"])
    sp_name = _normalize(spotify_track["name"])
    if not sp_artist or not sp_name:
        return []

    out = []
    for lf in lastfm_pool:
        lf_artist = _normalize(lf["artist"])
        if not lf_artist:
            continue
        artist_sim = _similarity(sp_artist, lf_artist)
        if artist_sim < 0.85:
            continue
        lf_name = _normalize(lf["name"])
        name_sim = _similarity(sp_name, lf_name)
        if name_sim < 0.5:
            continue
        score = name_sim * 0.8 + artist_sim * 0.2
        out.append(
            {
                "artist": lf["artist"],
                "name": lf["name"],
                "score": round(score, 3),
            }
        )
    out.sort(key=lambda c: c["score"], reverse=True)
    return out[:top_n]


async def compute_diff(spotify_client, lastfm_username: str) -> dict:
    """Compare Spotify Liked vs Last.fm Loved.

    Returns:
        {
          "ok": bool,
          "error": str | None,
          "needs_love": [{id, artist, name, lastfm_name}],   # Liked, not Loved
          "loved_not_liked": [{artist, name}],               # Loved, not Liked
          "spotify_total": int,
          "lastfm_total": int,
          "ignored_count": int,
        }
    """
    try:
        spotify_liked = await spotify_client.get_all_saved_tracks()
    except CredentialError as e:
        return {"ok": False, "error": f"Spotify auth: {e}"}
    except SpotifyAPIError as e:
        # A failed page would leave the Liked list incomplete; bail rather than
        # diff against partial data and mislabel tracks as "loved not liked".
        return {"ok": False, "error": f"Spotify: {e}"}

    loved = await get_loved_tracks(lastfm_username)
    if loved == LASTFM_ERROR:
        return {"ok": False, "error": "Could not reach Last.fm."}

    ignored = await get_loved_sync_ignored()
    aliases = await get_all_track_aliases()
    by_id = aliases["by_id"]
    by_artist_name = aliases["by_artist_name"]

    # Resolve each Spotify track to its Last.fm-equivalent name (alias if any).
    resolved = []
    for sp in spotify_liked:
        alias = by_id.get(sp["id"]) or by_artist_name.get((sp["artist"], sp["name"]))
        lookup_name = alias or sp["name"]
        resolved.append(
            {
                "id": sp["id"],
                "artist": sp["artist"],
                "name": sp["name"],
                "lastfm_name": lookup_name,
                "key": _norm_key(sp["artist"], lookup_name),
            }
        )

    spotify_keys = {r["key"] for r in resolved}
    lastfm_keys = {_norm_key(t["artist"], t["name"]) for t in loved}

    loved_not_liked = [
        {"artist": t["artist"], "name": t["name"]}
        for t in loved
        if _norm_key(t["artist"], t["name"]) not in spotify_keys
    ]
    loved_not_liked.sort(key=lambda x: (x["artist"].lower(), x["name"].lower()))

    needs_love = []
    for r in resolved:
        if r["key"] in lastfm_keys or r["id"] in ignored:
            continue
        candidates = find_candidates(
            {"artist": r["artist"], "name": r["name"]},
            loved_not_liked,
            top_n=5,
        )
        needs_love.append(
            {
                "id": r["id"],
                "artist": r["artist"],
                "name": r["name"],
                "lastfm_name": r["lastfm_name"],
                "candidates": candidates,
            }
        )
    needs_love.sort(key=lambda x: (x["artist"].lower(), x["name"].lower()))

    return {
        "ok": True,
        "error": None,
        "needs_love": needs_love,
        "loved_not_liked": loved_not_liked,
        "spotify_total": len(spotify_liked),
        "lastfm_total": len(loved),
        "ignored_count": len(ignored),
    }
