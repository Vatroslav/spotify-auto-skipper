"""
SQLite database setup and CRUD helpers.
All data persists at DATA_DIR/skipper.db (default: /app/data/skipper.db).
"""

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import aiosqlite

from app.encryption import decrypt, encrypt

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
    album_name  TEXT,
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

CREATE TABLE IF NOT EXISTS track_aliases (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id     TEXT,
    artist       TEXT NOT NULL,
    spotify_name TEXT NOT NULL,
    lastfm_name  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS overall_metrics (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    computed_at     TIMESTAMP NOT NULL,
    songs_played    INTEGER NOT NULL DEFAULT 0,
    songs_skipped   INTEGER NOT NULL DEFAULT 0,
    songs_kept      INTEGER NOT NULL DEFAULT 0,
    skip_rate       REAL NOT NULL DEFAULT 0,
    unique_songs    INTEGER NOT NULL DEFAULT 0,
    unique_artists  INTEGER NOT NULL DEFAULT 0,
    most_skipped_song   TEXT,
    most_skipped_artist TEXT,
    most_skipped_count  INTEGER,
    most_played_song    TEXT,
    most_played_artist  TEXT,
    most_played_count   INTEGER,
    longest_skip_streak INTEGER NOT NULL DEFAULT 0,
    avg_skip_days       REAL,
    total_days          INTEGER NOT NULL DEFAULT 0,
    oldest_scrobble_song    TEXT,
    oldest_scrobble_artist  TEXT,
    oldest_scrobble_days    INTEGER,
    oldest_scrobble_date    TEXT,
    busiest_day_date    TEXT,
    busiest_day_count   INTEGER,
    most_skips_day_date TEXT,
    most_skips_day_count INTEGER,
    highest_skip_rate_date  TEXT,
    highest_skip_rate_rate  REAL,
    longest_streak_day_date TEXT,
    longest_streak_day_streak INTEGER
);

CREATE TABLE IF NOT EXISTS mapping_fail_dismissals (
    track_id     TEXT PRIMARY KEY,
    dismissed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_track_events_timestamp ON track_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp);
"""


async def get_db() -> aiosqlite.Connection:
    """Open a connection with row_factory, WAL mode, and busy timeout."""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    await db.execute("PRAGMA foreign_keys=ON")
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

        # Migrate: add album_name to track_events
        cursor = await db.execute("PRAGMA table_info(track_events)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "album_name" not in columns:
            await db.execute("ALTER TABLE track_events ADD COLUMN album_name TEXT")

        # Migrate: add track_id to track_aliases and drop old UNIQUE(artist, spotify_name)
        cursor = await db.execute("PRAGMA table_info(track_aliases)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "track_id" not in columns:
            await db.executescript(
                """
                CREATE TABLE track_aliases_new (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    track_id     TEXT,
                    artist       TEXT NOT NULL,
                    spotify_name TEXT NOT NULL,
                    lastfm_name  TEXT NOT NULL
                );
                INSERT INTO track_aliases_new (id, artist, spotify_name, lastfm_name)
                    SELECT id, artist, spotify_name, lastfm_name FROM track_aliases;
                DROP TABLE track_aliases;
                ALTER TABLE track_aliases_new RENAME TO track_aliases;
                CREATE UNIQUE INDEX idx_track_aliases_track_id
                    ON track_aliases(track_id) WHERE track_id IS NOT NULL;
                """
            )

        # Migrate: mapping_fail_dismissals keyed by track_id instead of (artist, track_name)
        cursor = await db.execute("PRAGMA table_info(mapping_fail_dismissals)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "track_id" not in columns:
            await db.executescript(
                """
                DROP TABLE mapping_fail_dismissals;
                CREATE TABLE mapping_fail_dismissals (
                    track_id     TEXT PRIMARY KEY,
                    dismissed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

        # Indexes that depend on columns added above must run after migrations
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_track_aliases_track_id "
            "ON track_aliases(track_id) WHERE track_id IS NOT NULL"
        )

        await db.commit()
    finally:
        await db.close()


# ── Track Aliases ────────────────────────────────────────────────


async def get_track_alias(track_id: str, artist: str = "", spotify_name: str = "") -> str | None:
    """Return the Last.fm name for a track.

    Primary lookup: by Spotify track_id (unambiguous — each album version of
    a song has its own id). Falls back to (artist, spotify_name) match on
    legacy rows that predate track_id (track_id IS NULL in those).
    """
    db = await get_db()
    try:
        if track_id:
            cursor = await db.execute(
                "SELECT lastfm_name FROM track_aliases WHERE track_id = ?",
                (track_id,),
            )
            row = await cursor.fetchone()
            if row:
                return row["lastfm_name"]

        if artist and spotify_name:
            cursor = await db.execute(
                "SELECT lastfm_name FROM track_aliases WHERE track_id IS NULL AND artist = ? AND spotify_name = ?",
                (artist, spotify_name),
            )
            row = await cursor.fetchone()
            if row:
                return row["lastfm_name"]

        return None
    finally:
        await db.close()


async def add_track_alias(track_id: str, artist: str, spotify_name: str, lastfm_name: str):
    """Upsert a Spotify-to-Last.fm track name mapping, keyed by track_id."""
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO track_aliases (track_id, artist, spotify_name, lastfm_name)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(track_id) DO UPDATE SET
                   artist = excluded.artist,
                   spotify_name = excluded.spotify_name,
                   lastfm_name = excluded.lastfm_name""",
            (track_id, artist, spotify_name, lastfm_name),
        )
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
    track_id: str,
    track_name: str,
    artist_name: str,
    outcome: str,
    days_ago: int | None = None,
    context_uri: str | None = None,
    album_name: str | None = None,
):
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO track_events (track_id, track_name, artist_name, album_name, outcome, days_ago, context_uri)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (track_id, track_name, artist_name, album_name, outcome, days_ago, context_uri),
        )
        await db.commit()
    finally:
        await db.close()


async def get_last_track_event_id() -> str | None:
    """Return the track_id of the most recent track event, or None."""
    db = await get_db()
    try:
        row = await (await db.execute("SELECT track_id FROM track_events ORDER BY id DESC LIMIT 1")).fetchone()
        return row[0] if row else None
    finally:
        await db.close()


async def get_track_events(date_str: str, tz: str = "") -> list[dict]:
    """Get track events for a specific date (YYYY-MM-DD) in user's timezone."""
    utc_start, utc_end = _date_to_utc_range(date_str, tz)
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT id, timestamp, track_id, track_name, artist_name, outcome, days_ago, context_uri
               FROM track_events WHERE timestamp >= ? AND timestamp < ? ORDER BY timestamp""",
            (utc_start, utc_end),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_all_track_events() -> list[dict]:
    """Get ALL track events across all dates (for overall insights)."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT id, timestamp, track_id, track_name, artist_name, outcome, days_ago, context_uri
               FROM track_events ORDER BY timestamp"""
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_all_track_events_by_date(tz: str = "") -> list[tuple[str, list[dict]]]:
    """Get ALL track events grouped by date in user's timezone.

    Returns list of (date_str, [row_dicts]) tuples sorted by date.
    """
    try:
        tz_info = ZoneInfo(tz) if tz else None
    except Exception:
        tz_info = None
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT id, timestamp, track_id, track_name, artist_name, outcome, days_ago, context_uri
               FROM track_events ORDER BY timestamp"""
        )
        rows = await cursor.fetchall()
        by_date: dict[str, list[dict]] = {}
        for row in rows:
            r = dict(row)
            ts = r["timestamp"]
            if tz_info:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                local_date = dt.astimezone(tz_info).strftime("%Y-%m-%d")
            else:
                local_date = ts[:10]
            by_date.setdefault(local_date, []).append(r)
        return sorted(by_date.items())
    finally:
        await db.close()


async def get_track_event_dates(tz: str = "") -> list[str]:
    """Get list of dates that have track events, grouped by user's timezone."""
    try:
        tz_info = ZoneInfo(tz) if tz else None
    except Exception:
        tz_info = None
    db = await get_db()
    try:
        cursor = await db.execute("SELECT DISTINCT timestamp FROM track_events ORDER BY timestamp")
        rows = await cursor.fetchall()
        dates = set()
        for row in rows:
            ts = row["timestamp"]
            if tz_info:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                local_date = dt.astimezone(tz_info).strftime("%Y-%m-%d")
            else:
                local_date = ts[:10]
            dates.add(local_date)
        return sorted(dates)
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


def _date_to_utc_range(date_str: str, tz_name: str) -> tuple[str, str]:
    """Convert a local date + timezone into a UTC start/end range."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        # Fallback to UTC if timezone is invalid
        return date_str + " 00:00:00", date_str + " 23:59:59"
    local_start = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)
    local_end = local_start + timedelta(days=1)
    utc_start = local_start.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    utc_end = local_end.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return utc_start, utc_end


def _today_utc_range(tz_name: str) -> tuple[str, str]:
    """Get UTC range for 'today' in the user's timezone."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        # Fallback: use UTC today
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return today + " 00:00:00", today + " 23:59:59"
    now_local = datetime.now(tz)
    today_str = now_local.strftime("%Y-%m-%d")
    return _date_to_utc_range(today_str, tz_name)


async def get_logs(
    date_str: str = "",
    level: str = "all",
    tz: str = "",
    limit: int = 0,
    before_id: int = 0,
) -> list[dict]:
    db = await get_db()
    try:
        if date_str:
            utc_start, utc_end = _date_to_utc_range(date_str, tz)
        else:
            utc_start, utc_end = _today_utc_range(tz)

        base_where = "WHERE timestamp >= ? AND timestamp < ?"
        params: list = [utc_start, utc_end]

        if level not in ("all", "skipped", "kept"):
            base_where += " AND level = ?"
            params.append(level)

        if before_id:
            base_where += " AND id < ?"
            params.append(before_id)

        limit_clause = f"LIMIT {int(limit)}" if limit > 0 else ""

        # When using limit, fetch newest first then reverse for chronological order
        if limit > 0:
            cursor = await db.execute(
                f"SELECT id, timestamp, level, message FROM logs {base_where} ORDER BY timestamp DESC {limit_clause}",
                params,
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in reversed(rows)]
        else:
            cursor = await db.execute(
                f"SELECT id, timestamp, level, message FROM logs {base_where} ORDER BY timestamp",
                params,
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    finally:
        await db.close()


async def search_logs(query: str, date_str: str = "", tz: str = "") -> list[dict]:
    """Search logs for blocks where 'Currently playing:' matches query."""
    db = await get_db()
    try:
        if date_str:
            utc_start, utc_end = _date_to_utc_range(date_str, tz)
        else:
            utc_start, utc_end = None, None

        # Find all "Currently playing:" lines matching the query
        where = "WHERE message LIKE 'Currently playing:%' AND message LIKE ?"
        params: list = [f"%{query}%"]
        if utc_start and utc_end:
            where += " AND timestamp >= ? AND timestamp < ?"
            params.extend([utc_start, utc_end])

        cursor = await db.execute(
            f"SELECT id, timestamp, level, message FROM logs {where} ORDER BY timestamp",
            params,
        )
        headers = [dict(row) for row in await cursor.fetchall()]

        if not headers:
            return []

        # For each header, grab the next 4 lines (block context)
        results = []
        for header in headers:
            cursor = await db.execute(
                "SELECT id, timestamp, level, message FROM logs WHERE id > ? ORDER BY id LIMIT 4",
                (header["id"],),
            )
            following = [dict(row) for row in await cursor.fetchall()]
            block = [header]
            for row in following:
                if row["message"].startswith("Currently playing:"):
                    break
                block.append(row)
            results.extend(block)

        return results
    finally:
        await db.close()


async def get_log_dates() -> list[str]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT DISTINCT date(timestamp) as d FROM logs ORDER BY d")
        rows = await cursor.fetchall()
        return [row["d"] for row in rows]
    finally:
        await db.close()


async def purge_old_logs(retention_days: int):
    """Delete log entries older than retention_days. Track events are kept permanently."""
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM logs WHERE timestamp < datetime('now', ?)",
            (f"-{retention_days} days",),
        )
        await db.commit()
    finally:
        await db.close()


# ── Overall metrics cache ────────────────────────────────────────


async def recompute_overall_metrics():
    """Recompute all-time metrics via SQL and store in overall_metrics table."""
    db = await get_db()
    try:
        # Basic counts
        row = await (
            await db.execute(
                "SELECT COUNT(*) as total, SUM(outcome='skipped') as skipped, SUM(outcome!='skipped') as kept FROM track_events"
            )
        ).fetchone()
        total = row["total"] or 0
        skipped = row["skipped"] or 0
        kept = row["kept"] or 0
        skip_rate = (skipped / total * 100) if total > 0 else 0.0

        # Unique counts
        row = await (
            await db.execute("SELECT COUNT(DISTINCT artist_name || '|||' || track_name) as c FROM track_events")
        ).fetchone()
        unique_songs = row["c"] or 0

        row = await (await db.execute("SELECT COUNT(DISTINCT artist_name) as c FROM track_events")).fetchone()
        unique_artists = row["c"] or 0

        # Most skipped
        row = await (
            await db.execute(
                "SELECT artist_name, track_name, COUNT(*) as c FROM track_events WHERE outcome='skipped' GROUP BY artist_name, track_name ORDER BY c DESC LIMIT 1"
            )
        ).fetchone()
        ms_song, ms_artist, ms_count = (row["track_name"], row["artist_name"], row["c"]) if row else (None, None, None)

        # Most played
        row = await (
            await db.execute(
                "SELECT artist_name, track_name, COUNT(*) as c FROM track_events WHERE outcome!='skipped' GROUP BY artist_name, track_name ORDER BY c DESC LIMIT 1"
            )
        ).fetchone()
        mp_song, mp_artist, mp_count = (row["track_name"], row["artist_name"], row["c"]) if row else (None, None, None)

        # Avg skip age
        row = await (
            await db.execute(
                "SELECT AVG(days_ago) as a FROM track_events WHERE outcome='skipped' AND days_ago IS NOT NULL"
            )
        ).fetchone()
        avg_skip_days = row["a"]

        # Oldest scrobble
        row = await (
            await db.execute(
                "SELECT artist_name, track_name, days_ago, DATE(timestamp) as d FROM track_events WHERE days_ago IS NOT NULL ORDER BY days_ago DESC LIMIT 1"
            )
        ).fetchone()
        os_song, os_artist, os_days, os_date = (
            (row["track_name"], row["artist_name"], row["days_ago"], row["d"]) if row else (None, None, None, None)
        )

        # Total days
        row = await (await db.execute("SELECT COUNT(DISTINCT DATE(timestamp)) as c FROM track_events")).fetchone()
        total_days = row["c"] or 0

        # Busiest day
        row = await (
            await db.execute(
                "SELECT DATE(timestamp) as d, COUNT(*) as c FROM track_events GROUP BY d ORDER BY c DESC LIMIT 1"
            )
        ).fetchone()
        busiest_date, busiest_count = (row["d"], row["c"]) if row else (None, None)

        # Most skips in a day
        row = await (
            await db.execute(
                "SELECT DATE(timestamp) as d, COUNT(*) as c FROM track_events WHERE outcome='skipped' GROUP BY d ORDER BY c DESC LIMIT 1"
            )
        ).fetchone()
        most_skips_date, most_skips_count = (row["d"], row["c"]) if row else (None, None)

        # Highest skip rate day (min 5 songs)
        row = await (
            await db.execute(
                """SELECT DATE(timestamp) as d,
                      CAST(SUM(outcome='skipped') AS REAL) / COUNT(*) * 100 as rate
               FROM track_events GROUP BY d HAVING COUNT(*) >= 5 ORDER BY rate DESC LIMIT 1"""
            )
        ).fetchone()
        high_rate_date, high_rate_rate = (row["d"], row["rate"]) if row else (None, None)

        # Longest skip streak (Python — fetch outcomes in order)
        cursor = await db.execute("SELECT outcome FROM track_events ORDER BY timestamp")
        outcomes = await cursor.fetchall()
        longest_streak = 0
        current = 0
        for r in outcomes:
            if r["outcome"] == "skipped":
                current += 1
                if current > longest_streak:
                    longest_streak = current
            else:
                current = 0

        # Longest streak per day
        cursor = await db.execute("SELECT DATE(timestamp) as d, outcome FROM track_events ORDER BY timestamp")
        day_rows = await cursor.fetchall()
        best_streak_date, best_streak_val = None, 0
        cur_day, cur_streak, day_best = None, 0, 0
        for r in day_rows:
            d = r["d"]
            if d != cur_day:
                if day_best > best_streak_val:
                    best_streak_val = day_best
                    best_streak_date = cur_day
                cur_day, cur_streak, day_best = d, 0, 0
            if r["outcome"] == "skipped":
                cur_streak += 1
                if cur_streak > day_best:
                    day_best = cur_streak
            else:
                cur_streak = 0
        if day_best > best_streak_val:
            best_streak_val = day_best
            best_streak_date = cur_day

        # Write to cache
        await db.execute(
            """INSERT INTO overall_metrics (
                id, computed_at,
                songs_played, songs_skipped, songs_kept, skip_rate,
                unique_songs, unique_artists,
                most_skipped_song, most_skipped_artist, most_skipped_count,
                most_played_song, most_played_artist, most_played_count,
                longest_skip_streak, avg_skip_days, total_days,
                oldest_scrobble_song, oldest_scrobble_artist, oldest_scrobble_days, oldest_scrobble_date,
                busiest_day_date, busiest_day_count,
                most_skips_day_date, most_skips_day_count,
                highest_skip_rate_date, highest_skip_rate_rate,
                longest_streak_day_date, longest_streak_day_streak
            ) VALUES (1, datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                computed_at=excluded.computed_at,
                -- Aggregate metrics: always overwrite with fresh data
                songs_played=excluded.songs_played, songs_skipped=excluded.songs_skipped,
                songs_kept=excluded.songs_kept, skip_rate=excluded.skip_rate,
                unique_songs=excluded.unique_songs, unique_artists=excluded.unique_artists,
                avg_skip_days=excluded.avg_skip_days, total_days=excluded.total_days,
                -- Records: only overwrite if new value beats existing
                most_skipped_song=CASE WHEN excluded.most_skipped_count > COALESCE(overall_metrics.most_skipped_count, 0) THEN excluded.most_skipped_song ELSE overall_metrics.most_skipped_song END,
                most_skipped_artist=CASE WHEN excluded.most_skipped_count > COALESCE(overall_metrics.most_skipped_count, 0) THEN excluded.most_skipped_artist ELSE overall_metrics.most_skipped_artist END,
                most_skipped_count=MAX(COALESCE(overall_metrics.most_skipped_count, 0), excluded.most_skipped_count),
                most_played_song=CASE WHEN excluded.most_played_count > COALESCE(overall_metrics.most_played_count, 0) THEN excluded.most_played_song ELSE overall_metrics.most_played_song END,
                most_played_artist=CASE WHEN excluded.most_played_count > COALESCE(overall_metrics.most_played_count, 0) THEN excluded.most_played_artist ELSE overall_metrics.most_played_artist END,
                most_played_count=MAX(COALESCE(overall_metrics.most_played_count, 0), excluded.most_played_count),
                longest_skip_streak=MAX(COALESCE(overall_metrics.longest_skip_streak, 0), excluded.longest_skip_streak),
                oldest_scrobble_song=CASE WHEN excluded.oldest_scrobble_days > COALESCE(overall_metrics.oldest_scrobble_days, 0) THEN excluded.oldest_scrobble_song ELSE overall_metrics.oldest_scrobble_song END,
                oldest_scrobble_artist=CASE WHEN excluded.oldest_scrobble_days > COALESCE(overall_metrics.oldest_scrobble_days, 0) THEN excluded.oldest_scrobble_artist ELSE overall_metrics.oldest_scrobble_artist END,
                oldest_scrobble_days=MAX(COALESCE(overall_metrics.oldest_scrobble_days, 0), COALESCE(excluded.oldest_scrobble_days, 0)),
                oldest_scrobble_date=CASE WHEN excluded.oldest_scrobble_days > COALESCE(overall_metrics.oldest_scrobble_days, 0) THEN excluded.oldest_scrobble_date ELSE overall_metrics.oldest_scrobble_date END,
                busiest_day_date=CASE WHEN excluded.busiest_day_count > COALESCE(overall_metrics.busiest_day_count, 0) THEN excluded.busiest_day_date ELSE overall_metrics.busiest_day_date END,
                busiest_day_count=MAX(COALESCE(overall_metrics.busiest_day_count, 0), excluded.busiest_day_count),
                most_skips_day_date=CASE WHEN excluded.most_skips_day_count > COALESCE(overall_metrics.most_skips_day_count, 0) THEN excluded.most_skips_day_date ELSE overall_metrics.most_skips_day_date END,
                most_skips_day_count=MAX(COALESCE(overall_metrics.most_skips_day_count, 0), excluded.most_skips_day_count),
                highest_skip_rate_date=CASE WHEN excluded.highest_skip_rate_rate > COALESCE(overall_metrics.highest_skip_rate_rate, 0) THEN excluded.highest_skip_rate_date ELSE overall_metrics.highest_skip_rate_date END,
                highest_skip_rate_rate=MAX(COALESCE(overall_metrics.highest_skip_rate_rate, 0), excluded.highest_skip_rate_rate),
                longest_streak_day_date=CASE WHEN excluded.longest_streak_day_streak > COALESCE(overall_metrics.longest_streak_day_streak, 0) THEN excluded.longest_streak_day_date ELSE overall_metrics.longest_streak_day_date END,
                longest_streak_day_streak=MAX(COALESCE(overall_metrics.longest_streak_day_streak, 0), excluded.longest_streak_day_streak)""",
            (
                total,
                skipped,
                kept,
                skip_rate,
                unique_songs,
                unique_artists,
                ms_song,
                ms_artist,
                ms_count,
                mp_song,
                mp_artist,
                mp_count,
                longest_streak,
                avg_skip_days,
                total_days,
                os_song,
                os_artist,
                os_days,
                os_date,
                busiest_date,
                busiest_count,
                most_skips_date,
                most_skips_count,
                high_rate_date,
                high_rate_rate,
                best_streak_date,
                best_streak_val,
            ),
        )
        await db.commit()
    finally:
        await db.close()


async def get_cached_overall_metrics() -> dict | None:
    """Read precomputed overall metrics. Returns None if not yet computed."""
    db = await get_db()
    try:
        row = await (await db.execute("SELECT * FROM overall_metrics WHERE id = 1")).fetchone()
        if not row:
            return None
        r = dict(row)

        def _top_track(song_key, artist_key, count_key):
            if r[song_key] is None:
                return None
            return {"song": r[song_key], "artist": r[artist_key], "count": r[count_key]}

        return {
            "songs_played": r["songs_played"],
            "songs_skipped": r["songs_skipped"],
            "songs_kept": r["songs_kept"],
            "skip_rate": r["skip_rate"],
            "unique_songs": r["unique_songs"],
            "unique_artists": r["unique_artists"],
            "most_skipped": _top_track("most_skipped_song", "most_skipped_artist", "most_skipped_count"),
            "most_played": _top_track("most_played_song", "most_played_artist", "most_played_count"),
            "longest_skip_streak": r["longest_skip_streak"],
            "avg_skip_days": r["avg_skip_days"],
            "total_days": r["total_days"],
            "oldest_scrobble": {
                "song": r["oldest_scrobble_song"],
                "artist": r["oldest_scrobble_artist"],
                "days_ago": r["oldest_scrobble_days"],
                "date": r["oldest_scrobble_date"],
            }
            if r["oldest_scrobble_song"]
            else None,
            "busiest_day": {"date": r["busiest_day_date"], "count": r["busiest_day_count"]},
            "most_skips_day": {"date": r["most_skips_day_date"], "count": r["most_skips_day_count"]},
            "highest_skip_rate_day": {"date": r["highest_skip_rate_date"], "rate": r["highest_skip_rate_rate"]},
            "longest_streak_day": {"date": r["longest_streak_day_date"], "streak": r["longest_streak_day_streak"]},
        }
    finally:
        await db.close()


# ── OAuth tokens ─────────────────────────────────────────────────


async def get_oauth_tokens() -> dict | None:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT access_token, refresh_token, expires_at FROM oauth_tokens WHERE id = 1")
        row = await cursor.fetchone()
        if not row:
            return None
        return {
            "access_token": decrypt(row["access_token"]) if row["access_token"] else "",
            "refresh_token": decrypt(row["refresh_token"]) if row["refresh_token"] else "",
            "expires_at": row["expires_at"],
        }
    finally:
        await db.close()


async def clear_oauth_tokens():
    """Delete all stored OAuth tokens."""
    db = await get_db()
    try:
        await db.execute("DELETE FROM oauth_tokens")
        await db.commit()
    finally:
        await db.close()


async def save_oauth_tokens(access_token: str, refresh_token: str, expires_at: str):
    enc_access = encrypt(access_token) if access_token else ""
    enc_refresh = encrypt(refresh_token) if refresh_token else ""
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO oauth_tokens (id, access_token, refresh_token, expires_at)
               VALUES (1, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET access_token = ?, refresh_token = ?, expires_at = ?""",
            (enc_access, enc_refresh, expires_at, enc_access, enc_refresh, expires_at),
        )
        await db.commit()
    finally:
        await db.close()


# ── Mapping fail candidates ──────────────────────────────────────


async def get_mapping_fail_candidates(skip_window_days: int) -> list[dict]:
    """Return tracks likely suffering from Last.fm mapping issues.

    A candidate is a Spotify track (identified by track_id) that appears
    2+ times within the skip window where every occurrence has outcome
    'played' or 'no_scrobble' (never 'skipped', 'liked', 'never_skip',
    'skip_paused'). Grouping by track_id lets different album versions
    of the same-named track be handled independently.

    Dismissed entries are filtered: a dismissal hides the track until new
    qualifying events are logged after dismissed_at.
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            WITH recent AS (
                SELECT track_id, track_name, artist_name, album_name, outcome, timestamp
                FROM track_events
                WHERE timestamp >= datetime('now', ?)
            ),
            grouped AS (
                SELECT
                    r.track_id,
                    r.track_name,
                    r.artist_name,
                    MAX(r.album_name) AS album_name,
                    COUNT(*) AS total_count,
                    SUM(r.outcome = 'no_scrobble') AS no_scrobble_count,
                    SUM(r.outcome = 'played') AS played_count,
                    MAX(r.timestamp) AS last_seen
                FROM recent r
                LEFT JOIN mapping_fail_dismissals d ON d.track_id = r.track_id
                WHERE r.outcome IN ('played', 'no_scrobble')
                  AND (d.dismissed_at IS NULL OR r.timestamp > d.dismissed_at)
                GROUP BY r.track_id
            )
            SELECT track_id, track_name, artist_name, album_name,
                   total_count, no_scrobble_count, played_count, last_seen
            FROM grouped
            WHERE total_count >= 2
              AND NOT EXISTS (
                  SELECT 1 FROM track_events te
                  WHERE te.track_id = grouped.track_id
                    AND te.timestamp >= datetime('now', ?)
                    AND te.outcome IN ('skipped', 'liked', 'never_skip', 'skip_paused')
              )
            ORDER BY total_count DESC, last_seen DESC
            """,
            (f"-{skip_window_days} days", f"-{skip_window_days} days"),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def dismiss_mapping_fail(track_id: str):
    """Mark a Spotify track as dismissed from the mapping-fails view."""
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO mapping_fail_dismissals (track_id)
               VALUES (?)
               ON CONFLICT(track_id)
               DO UPDATE SET dismissed_at = CURRENT_TIMESTAMP""",
            (track_id,),
        )
        await db.commit()
    finally:
        await db.close()
