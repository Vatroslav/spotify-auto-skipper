"""
Playlist genre mix — which genres dominate a playlist.

Pipeline: playlist -> primary artist of each track -> that artist's Spotify
genres -> tally. Every genre Spotify returns for an artist is counted (the list
already comes back ordered by relevance, and is rarely longer than five).

Two tallies are produced because they answer different questions:
  - ``tracks``  — how much of the playlist *plays* as this genre
  - ``artists`` — how much of the roster *is* this genre

A 40-track prog obsession and 40 one-track pop artists look identical on
``artists`` and nothing alike on ``tracks``, so neither number alone is the
answer.
"""


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


async def compute_genre_stats(spotify_client, playlist_id: str) -> dict:
    """Return the genre breakdown of a playlist.

    Raises ``CredentialError`` / ``SpotifyAPIError`` from the client — a failed
    page must not degrade into a partial tally, which would read as a real
    result while quietly under-counting whole genres.
    """
    playlist = await spotify_client.get_playlist_artist_counts(playlist_id)
    artists = playlist["artists"]

    genres_by_artist = await spotify_client.get_artists_genres(list(artists.keys())) if artists else {}
    tally = _tally(artists, genres_by_artist)

    counted_tracks = playlist["total_tracks"] - playlist["tracks_without_artist"]

    return {
        "total_tracks": playlist["total_tracks"],
        "counted_tracks": counted_tracks,
        "tracks_without_artist": playlist["tracks_without_artist"],
        "artist_count": len(artists),
        "artists_without_genres": tally["artists_without_genres"],
        "tracks_without_genres": tally["tracks_without_genres"],
        "genres": tally["genres"],
    }
