"""
In-memory application state shared between the worker and API routes.
Replaces desktop app's utils.py shared mutable state.
"""

import asyncio
from datetime import datetime


class AppState:
    def __init__(self):
        self.skipping_paused: bool = False
        self.last_checked_track_id: str | None = None
        self.last_checked_timestamp: datetime | None = None
        self.current_track: dict | None = None
        self.worker_running: bool = False
        self.check_now_event: asyncio.Event = asyncio.Event()
        self.recent_skip_days: list[int] = []
        self.last_check_message: str | None = None
        self.idle_mode: bool = False
        self.skip_exempt_track_id: str | None = None
        self.spotify_client = None  # Shared SpotifyClient, set during lifespan
        self.worker_task: asyncio.Task | None = None  # Reference to polling_loop task
        self.supervisor_task: asyncio.Task | None = None  # Watches/restarts worker on crash

        # Liked-status cache for the dashboard poll. Single-entry (holds only the
        # most recently queried track_id) so it never accumulates stale ids. Avoids
        # a Spotify /me/tracks/contains call on every 5s poll; a new track is a miss.
        self.liked_status_cache: dict[str, bool] = {}

        # Playlist Genres
        self.genres_task: asyncio.Task | None = None
        self.genres_status: str = "idle"  # idle/running/completed/failed
        self.genres_progress: dict = {}  # {current, total, message}
        self.genres_result: dict | None = None

        # Rediscovery
        self.rediscovery_task: asyncio.Task | None = None
        self.rediscovery_status: str = "idle"  # idle/running/completed/failed
        self.rediscovery_progress: dict = {}  # {phase, current, total, message}
        self.rediscovery_results: list = []  # track dicts that passed filter
        self.rediscovery_playlist_url: str | None = None

    def restart_worker_if_dead(self):
        """Restart the polling loop if it has stopped (e.g. after CredentialError)."""
        if self.worker_task is None or self.worker_task.done():
            from app.worker import polling_loop

            self.worker_task = asyncio.create_task(polling_loop())
            self.worker_running = True

    async def interruptible_sleep(self, seconds: float):
        """Sleep that can be interrupted by check_now_event."""
        try:
            await asyncio.wait_for(self.check_now_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass
        self.check_now_event.clear()


# Singleton
app_state = AppState()
