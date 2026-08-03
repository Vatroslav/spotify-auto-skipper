"""
Playlist genre mix — which genres dominate a playlist.

Pipeline: playlist -> primary artist of each track -> that artist's genres ->
tally. Two sources, picked by the user:

  * ``spotify`` — the artist object's ``genres`` array. Batched 50 at a time,
    so a 600-artist playlist is ~13 requests. Coarse: Spotify classifies a
    whole scene under one broad label.
  * ``lastfm``  — crowd-sourced top tags. No batch endpoint exists, so it costs
    one request per artist, cached in ``artist_tags``. Far more granular, and
    noisy in a way Spotify's curated list is not — hence the filter below.

Two tallies are produced because they answer different questions:
  - ``tracks``  — how much of the playlist *plays* as this genre
  - ``artists`` — how much of the roster *is* this genre

A 40-track prog obsession and 40 one-track pop artists look identical on
``artists`` and nothing alike on ``tracks``, so neither number alone is the
answer.
"""

import asyncio
import re

import httpx

from app.database import get_cached_artist_tags, save_artist_tags
from app.lastfm_api import LASTFM_ERROR, get_artist_top_tags

SOURCE_SPOTIFY = "spotify"
SOURCE_LASTFM = "lastfm"
SOURCES = (SOURCE_SPOTIFY, SOURCE_LASTFM)

# ── Last.fm tag filtering ────────────────────────────────────────
#
# Last.fm tags are whatever listeners typed, so the top of an artist's list
# mixes real genres with collection-keeping, sentiment and trivia. These are
# the non-genre categories that actually show up at high weight; everything
# else is kept, because guessing at "is this a genre" beyond a deny-list starts
# discarding real subgenres.

_TAG_NOISE = {
    # collection / listening habits
    "seen live", "favorites", "favourites", "favorite", "favourite",
    "favorite songs", "favourite songs", "favorite bands", "favourite bands",
    "favorite artists", "favourite artists", "albums i own", "i own it",
    "vinyl", "cd", "mp3", "spotify", "itunes", "want to see live",
    "under 2000 listeners", "my music", "music", "check out", "to check out",
    "recommended", "radio", "playlist",
    # sentiment
    "awesome", "amazing", "beautiful", "epic", "masterpiece", "cool", "good",
    "great", "best", "love", "loved", "love at first listen", "sexy",
    "brilliant", "genius", "perfect", "favorites songs",
    # bare nationality — compound tags like "norwegian black metal" are kept,
    # because there the nationality is part of a real scene name
    "norwegian", "swedish", "finnish", "german", "french", "polish", "russian",
    "greek", "italian", "american", "british", "english", "canadian", "usa",
    "uk", "japanese", "australian", "dutch", "belgian", "portuguese",
    "spanish", "czech", "ukrainian", "austrian", "swiss", "danish",
    "icelandic", "brazilian", "chilean", "hungarian", "romanian", "irish",
    # lineup / vocal descriptors
    "female vocalists", "female vocalist", "male vocalists", "male vocalist",
    "female voices", "female fronted", "one man band",
    # misc non-genre
    "underground", "obscure", "rare", "old school", "new", "other", "misc",
}

# Decades and bare years: 90s, 00s, 2010s, 1994
_TAG_YEAR_RE = re.compile(r"^(19|20)?\d{2}s?$|^\d{4}$")

# Last.fm normalises an artist's top tag to 100. Below this the tail is mostly
# one-off tags from a single listener.
TAG_MIN_COUNT = 25
TAG_MAX_PER_ARTIST = 5

# Last.fm asks for no more than ~5 requests/second.
LASTFM_CONCURRENCY = 4
LASTFM_DELAY = 0.2


def filter_tags(tags: list[dict]) -> list[str]:
    """Reduce raw Last.fm tags to genre-ish ones, strongest first."""
    out: list[str] = []
    for t in tags:
        name = (t.get("name") or "").strip().lower()
        count = t.get("count") or 0
        if not name or count < TAG_MIN_COUNT:
            continue
        if name in _TAG_NOISE or _TAG_YEAR_RE.match(name):
            continue
        if name not in out:
            out.append(name)
        if len(out) >= TAG_MAX_PER_ARTIST:
            break
    return out


def _tally(artists: dict[str, dict], genres_by_artist: dict[str, list[str]]) -> dict:
    """Fold artists + their genres into per-genre counts."""
    genres: dict[str, dict] = {}
    artists_without_genres = 0
    tracks_without_genres = 0

    for artist_id, info in artists.items():
        artist_genres = genres_by_artist.get(artist_id) or []
        track_count = info["track_count"]

        if not artist_genres:
            artists_without_genres += 1
            tracks_without_genres += track_count
            continue

        for genre in artist_genres:
            slot = genres.setdefault(genre, {"genre": genre, "artists": 0, "tracks": 0, "top_artists": []})
            slot["artists"] += 1
            slot["tracks"] += track_count
            slot["top_artists"].append((track_count, info["name"]))

    rows = []
    for slot in genres.values():
        slot["top_artists"].sort(key=lambda pair: (-pair[0], pair[1].lower()))
        rows.append(
            {
                "genre": slot["genre"],
                "artists": slot["artists"],
                "tracks": slot["tracks"],
                "top_artists": [name for _, name in slot["top_artists"][:3]],
            }
        )
    rows.sort(key=lambda row: (-row["tracks"], -row["artists"], row["genre"]))

    return {
        "genres": rows,
        "artists_without_genres": artists_without_genres,
        "tracks_without_genres": tracks_without_genres,
    }


async def _lastfm_genres(artists: dict[str, dict], progress=None) -> tuple[dict[str, list[str]], int]:
    """Return ``({artist_id: [tags]}, lookup_failures)``, using and filling the cache.

    Failures are counted rather than raised: one unreachable artist should not
    void a 600-artist scan. They are also NOT cached, so the next run retries
    them, unlike a genuine "Last.fm has no tags for this artist" empty result.
    """
    cached = await get_cached_artist_tags(list(artists.keys()))
    missing = [(aid, info["name"]) for aid, info in artists.items() if aid not in cached]

    result = dict(cached)
    failures = 0
    if not missing:
        if progress:
            progress(len(artists), len(artists), f"Genres from cache for {len(artists)} artists")
        return result, failures

    done = len(cached)
    total = len(artists)
    if progress:
        progress(done, total, f"Fetching Last.fm tags... {done}/{total}")

    fetched: list[tuple[str, str, list[str]]] = []
    sem = asyncio.Semaphore(LASTFM_CONCURRENCY)
    lock = asyncio.Lock()

    async with httpx.AsyncClient(timeout=20) as http:

        async def one(artist_id: str, name: str):
            nonlocal done, failures
            async with sem:
                raw = await get_artist_top_tags(name, http=http)
                await asyncio.sleep(LASTFM_DELAY)  # stay under Last.fm's rate limit
            async with lock:
                if raw is LASTFM_ERROR:
                    failures += 1
                else:
                    tags = filter_tags(raw)
                    result[artist_id] = tags
                    fetched.append((artist_id, name, tags))
                done += 1
                if progress:
                    progress(done, total, f"Fetching Last.fm tags... {done}/{total}")

        await asyncio.gather(*(one(aid, name) for aid, name in missing))

    await save_artist_tags(fetched)
    return result, failures


async def compute_genre_stats(
    spotify_client,
    playlist_id: str,
    source: str = SOURCE_SPOTIFY,
    progress=None,
) -> dict:
    """Return the genre breakdown of a playlist.

    ``progress`` is an optional ``callable(current, total, message)`` used to
    drive the job's progress bar.

    Raises ``CredentialError`` / ``SpotifyAPIError`` from the Spotify client — a
    failed page must not degrade into a partial tally, which would read as a
    real result while quietly under-counting whole genres. Last.fm failures are
    the exception to that: they are per-artist and counted, not fatal.
    """
    if source not in SOURCES:
        raise ValueError(f"Unknown genre source: {source}")

    if progress:
        progress(0, 0, "Reading playlist...")
    playlist = await spotify_client.get_playlist_artist_counts(playlist_id)
    artists = playlist["artists"]

    lookup_failures = 0
    if not artists:
        genres_by_artist: dict[str, list[str]] = {}
    elif source == SOURCE_LASTFM:
        genres_by_artist, lookup_failures = await _lastfm_genres(artists, progress=progress)
    else:
        if progress:
            progress(0, len(artists), f"Fetching Spotify genres for {len(artists)} artists...")
        genres_by_artist = await spotify_client.get_artists_genres(list(artists.keys()))
        if progress:
            progress(len(artists), len(artists), "Tallying...")

    tally = _tally(artists, genres_by_artist)
    counted_tracks = playlist["total_tracks"] - playlist["tracks_without_artist"]

    return {
        "source": source,
        "total_tracks": playlist["total_tracks"],
        "counted_tracks": counted_tracks,
        "tracks_without_artist": playlist["tracks_without_artist"],
        "artist_count": len(artists),
        "artists_without_genres": tally["artists_without_genres"],
        "tracks_without_genres": tally["tracks_without_genres"],
        "lookup_failures": lookup_failures,
        "genres": tally["genres"],
    }
