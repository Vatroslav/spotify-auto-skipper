"""
Pair the worker's plays (track_events) with Last.fm scrobbles by time and
artist, not by track name.

A name lookup fails exactly where it matters: a track Last.fm files under
another name ("Darker Days - Remastered" for Spotify's "Darker Days") never
looks heard. Pairing by time sees those plays, and tells which Last.fm name
each one was scrobbled under. Used by the Rediscovery clean-up (was this track
heard?) and by Mapping issues (which name does Last.fm use for it?).

A scrobble is stamped with the moment its track started; the worker logs its
track_events row once it has checked the track, a little later (on production
2 s to 4 min later, median about a minute). So a scrobble belongs to the
earliest same-artist event logged within the window below after its start.

Measured on production over 60 days (2026-09-24): 3,784 of 3,926 scrobbles
paired. It is not exact: when a same-artist track was skipped before it
scrobbled, the next one's scrobble can land on it. Treat a pairing as strong
evidence, not proof.
"""

import bisect

PAIR_EARLY = 10  # seconds an event may precede its scrobble: clock skew only
PAIR_LATE = 1800  # the worker caught the track late: restart, un-pause, idle polling
# The worker logs a skip after skipping, when the next track has already
# started, so a skipped event must trail the scrobble it claims by more than that.
SKIPPED_MIN_LAG = 30


def _loose(name: str) -> str:
    """Letters and digits only, casefolded: "Darker Days - Remastered" → "darkerdaysremastered"."""
    return "".join(ch for ch in name.casefold() if ch.isalnum())


def same_song(a: str, b: str) -> bool:
    """Whether one name extends the other ("Darker Days" / "Darker Days - Remastered")."""
    a, b = _loose(a), _loose(b)
    return bool(a) and bool(b) and (a.startswith(b) or b.startswith(a))


def pair_plays(events: list[dict], scrobbles: list[dict]) -> list[tuple[dict, dict]]:
    """(event, scrobble) for every worker event that has a scrobble of its own.

    ``events`` are track_events rows oldest first, with ``uts`` (unix seconds),
    ``artist_name``, ``track_name`` and ``outcome``. ``scrobbles`` are dicts
    with ``artist``, ``name`` and ``uts``.

    Each scrobble, oldest first, goes to the earliest unclaimed event of the
    same artist inside its window. When an album plays through several fit,
    and one whose name matches the scrobble's wins.
    """
    times = [e["uts"] for e in events]
    claimed: dict[int, dict] = {}
    for s in sorted(scrobbles, key=lambda s: s["uts"]):
        artist = s["artist"].casefold()
        fits = []
        for i in range(bisect.bisect_left(times, s["uts"] - PAIR_EARLY), len(events)):
            e = events[i]
            lag = e["uts"] - s["uts"]
            if lag > PAIR_LATE:
                break
            if i in claimed or e["artist_name"].casefold() != artist:
                continue
            if e["outcome"] == "skipped" and lag < SKIPPED_MIN_LAG:
                continue
            fits.append(i)
        if fits:
            claimed[next((i for i in fits if same_song(events[i]["track_name"], s["name"])), fits[0])] = s
    return [(events[i], claimed[i]) for i in sorted(claimed)]
