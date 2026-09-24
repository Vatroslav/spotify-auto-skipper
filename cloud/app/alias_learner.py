"""
Automatic aliases for the Mapping issues list.

Every LEARN_INTERVAL this takes the Mapping issues candidates and, for each one
that carries a suggested Last.fm name (see app.mapping_fails), stores that name
as an *unconfirmed* alias — the same kind the Like button creates. It is live
at once, so the worker finds the track's scrobbles from then on, and it waits
under Insights → Unconfirmed aliases for the user to confirm, edit or delete.

Why only Mapping issues candidates: there the suggestion was right every time
(2026-09-24, 67 of 67 saved unchanged). A candidate needs two or more plays the
name lookup could not explain, which a one-off mispairing does not produce.
Across all mismatched tracks with a single play, 9 of 20 pairings were a
different song by the same artist — those are left alone.

Never touched: a track that already has an alias (confirmed or not — it is the
user's or the Like button's call), and a track ever dismissed from Mapping
issues. Deleting an unconfirmed alias dismisses its track too, so a rejected
suggestion is not created again.
"""

import asyncio
import logging

from app.config import load_settings
from app.database import add_log, add_track_alias, get_dismissed_track_ids, get_track_alias
from app.mapping_fails import get_mapping_fail_candidates
from app.observability import report_exception

logger = logging.getLogger(__name__)

LEARN_INTERVAL = 6 * 3600  # seconds; Mapping issues gain candidates slowly
FIRST_RUN_DELAY = 600  # seconds after startup, to stay out of the worker's way


async def learn_aliases() -> int:
    """Store an unconfirmed alias for each eligible candidate. Returns how many were stored."""
    settings = await load_settings()
    candidates = await get_mapping_fail_candidates(settings["skip_window_days"])
    dismissed = await get_dismissed_track_ids()

    stored = 0
    for c in candidates:
        name = c["suggested_lastfm_name"]
        if not name or c["track_id"] in dismissed:
            continue
        if await get_track_alias(c["track_id"], c["artist_name"], c["track_name"]):
            continue
        await add_track_alias(c["track_id"], c["artist_name"], c["track_name"], name, user_confirmed=False)
        await add_log(
            f"Auto alias: {c['artist_name']} – {c['track_name']} → {name} (review under Insights → Unconfirmed aliases)"
        )
        stored += 1
    return stored


async def alias_learner_loop():
    """Run learn_aliases every LEARN_INTERVAL. A failed run is reported and retried next time."""
    await asyncio.sleep(FIRST_RUN_DELAY)
    while True:
        try:
            await learn_aliases()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[AliasLearner] Run failed: %s", e)
            report_exception(e, component="alias_learner")
        await asyncio.sleep(LEARN_INTERVAL)
