"""
Loved Sync — diff Spotify Liked Songs against Last.fm Loved Tracks.

Matching mirrors the worker's skip-check logic: each Spotify track is keyed by
(artist, alias_or_track_name) where the alias comes from the track_aliases
table (manual user-defined corrections). The same key is used to look up the
Last.fm Loved set.
"""

from app.database import get_all_track_aliases, get_loved_sync_ignored
from app.lastfm_api import LASTFM_ERROR, get_loved_tracks
from app.spotify_api import CredentialError


def _norm_key(artist: str, name: str) -> tuple[str, str]:
    return (artist.strip().lower(), name.strip().lower())


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

    needs_love = [
        {
            "id": r["id"],
            "artist": r["artist"],
            "name": r["name"],
            "lastfm_name": r["lastfm_name"],
        }
        for r in resolved
        if r["key"] not in lastfm_keys and r["id"] not in ignored
    ]
    needs_love.sort(key=lambda x: (x["artist"].lower(), x["name"].lower()))

    loved_not_liked = [
        {"artist": t["artist"], "name": t["name"]}
        for t in loved
        if _norm_key(t["artist"], t["name"]) not in spotify_keys
    ]
    loved_not_liked.sort(key=lambda x: (x["artist"].lower(), x["name"].lower()))

    return {
        "ok": True,
        "error": None,
        "needs_love": needs_love,
        "loved_not_liked": loved_not_liked,
        "spotify_total": len(spotify_liked),
        "lastfm_total": len(loved),
        "ignored_count": len(ignored),
    }
