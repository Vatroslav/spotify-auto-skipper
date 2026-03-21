"""
SQLite database setup and CRUD helpers.
All data persists at DATA_DIR/skipper.db (default: /app/data/skipper.db).
"""

import os
import json
import aiosqlite
from datetime import datetime, timezone

DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
DB_PATH = os.path.join(DATA_DIR, "skipper.db")

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS never_skip_artists (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    image_url TEXT DEFAULT '',
    added_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS track_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    track_id    TEXT NOT NULL,
    track_name  TEXT NOT NULL,
    artist_name TEXT NOT NULL,
    outcome     TEXT NOT NULL,
    days_ago    INTEGER,
    context_uri TEXT
);

CREATE TABLE IF NOT EXISTS logs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    level     TEXT NOT NULL DEFAULT 'info',
    message   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    access_token  TEXT,
    refresh_token TEXT,
    expires_at    TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_track_events_timestamp ON track_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp);
"""


async def get_db() -> aiosqlite.Connection:
    """Open a connection with row_factory enabled."""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def init_db():
    """Create tables and seed defaults if needed."""
    os.makedirs(DATA_DIR, exist_ok=True)
    db = await get_db()
    try:
        await db.executescript(_CREATE_TABLES)
        # Migrate: add image_url column if missing
        cursor = await db.execute("PRAGMA table_info(never_skip_artists)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "image_url" not in columns:
            await db.execute("ALTER TABLE never_skip_artists ADD COLUMN image_url TEXT DEFAULT ''")
        await db.commit()
    finally:
        await db.close()


# ── Settings CRUD ────────────────────────────────────────────────

async def get_setting(key: str, default=None):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        if row is None:
            return default
        return row["value"]
    finally:
        await db.close()


async def set_setting(key: str, value):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
            (key, str(value), str(value)),
        )
        await db.commit()
    finally:
        await db.close()


async def get_all_settings() -> dict:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
        return {row["key"]: row["value"] for row in rows}
    finally:
        await db.close()


async def set_many_settings(settings: dict):
    db = await get_db()
    try:
        for key, value in settings.items():
            await db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
                (key, str(value), str(value)),
            )
        await db.commit()
    finally:
        await db.close()


# ── Never-skip artists CRUD ─────────────────────────────────────

async def get_never_skip_artists() -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id, name, image_url, added_at FROM never_skip_artists ORDER BY name")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def add_never_skip_artist(artist_id: str, name: str, image_url: str = ""):
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO never_skip_artists (id, name, image_url) VALUES (?, ?, ?)",
            (artist_id, name, image_url),
        )
        await db.commit()
    finally:
        await db.close()


async def remove_never_skip_artist(artist_id: str):
    db = await get_db()
    try:
        await db.execute("DELETE FROM never_skip_artists WHERE id = ?", (artist_id,))
        await db.commit()
    finally:
        await db.close()


async def is_artist_never_skipped(artist_ids: list[str]) -> bool:
    if not artist_ids:
        return False
    db = await get_db()
    try:
        placeholders = ",".join("?" for _ in artist_ids)
        cursor = await db.execute(
            f"SELECT COUNT(*) as cnt FROM never_skip_artists WHERE id IN ({placeholders})",
            artist_ids,
        )
        row = await cursor.fetchone()
        return row["cnt"] > 0
    finally:
        await db.close()


# ── Track events ─────────────────────────────────────────────────

async def add_track_event(
    track_id: str, track_name: str, artist_name: str,
    outcome: str, days_ago: int | None = None, context_uri: str | None = None,
):
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO track_events (track_id, track_name, artist_name, outcome, days_ago, context_uri)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (track_id, track_name, artist_name, outcome, days_ago, context_uri),
        )
        await db.commit()
    finally:
        await db.close()


async def get_track_events(date_str: str) -> list[dict]:
    """Get track events for a specific date (YYYY-MM-DD)."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT id, timestamp, track_id, track_name, artist_name, outcome, days_ago, context_uri
               FROM track_events WHERE date(timestamp) = ? ORDER BY timestamp""",
            (date_str,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_track_event_dates() -> list[str]:
    """Get list of dates that have track events."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT DISTINCT date(timestamp) as d FROM track_events ORDER BY d"
        )
        rows = await cursor.fetchall()
        return [row["d"] for row in rows]
    finally:
        await db.close()


# ── Logs ─────────────────────────────────────────────────────────

async def add_log(message: str, level: str = "info"):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO logs (level, message) VALUES (?, ?)",
            (level, message),
        )
        await db.commit()
    finally:
        await db.close()


async def get_logs(date_str: str, level: str = "all") -> list[dict]:
    db = await get_db()
    try:
        if level == "all":
            cursor = await db.execute(
                """SELECT id, timestamp, level, message FROM logs
                   WHERE date(timestamp) = ? ORDER BY timestamp""",
                (date_str,),
            )
        else:
            cursor = await db.execute(
                """SELECT id, timestamp, level, message FROM logs
                   WHERE date(timestamp) = ? AND level = ? ORDER BY timestamp""",
                (date_str, level),
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_log_dates() -> list[str]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT DISTINCT date(timestamp) as d FROM logs ORDER BY d"
        )
        rows = await cursor.fetchall()
        return [row["d"] for row in rows]
    finally:
        await db.close()


async def purge_old_logs(retention_days: int):
    """Delete log entries and track events older than retention_days."""
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM logs WHERE timestamp < datetime('now', ?)",
            (f"-{retention_days} days",),
        )
        await db.execute(
            "DELETE FROM track_events WHERE timestamp < datetime('now', ?)",
            (f"-{retention_days} days",),
        )
        await db.commit()
    finally:
        await db.close()


# ── OAuth tokens ─────────────────────────────────────────────────

async def get_oauth_tokens() -> dict | None:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT access_token, refresh_token, expires_at FROM oauth_tokens WHERE id = 1"
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def save_oauth_tokens(access_token: str, refresh_token: str, expires_at: str):
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO oauth_tokens (id, access_token, refresh_token, expires_at)
               VALUES (1, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET access_token = ?, refresh_token = ?, expires_at = ?""",
            (access_token, refresh_token, expires_at,
             access_token, refresh_token, expires_at),
        )
        await db.commit()
    finally:
        await db.close()
