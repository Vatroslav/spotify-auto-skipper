"""
In-memory application state shared between the worker and API routes.
Replaces desktop app's utils.py shared mutable state.
"""

import asyncio
from datetime import datetime, timezone


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
        self.spotify_client = None  # Shared SpotifyClient, set during lifespan
        self.worker_task: asyncio.Task | None = None  # Reference to polling_loop task

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
