---
name: sqlite-migration
description: How to change the SQLite schema in cloud/app/database.py - new columns, tables, indexes, or constraint changes. Use for ANY schema change. The migration pattern here has two known startup-crash traps (index-before-migration, upsert on a partial unique index) that this playbook prevents.
---

# SQLite schema changes

There is no migration framework. `init_db()` runs on **every startup** against the live production database (Docker volume `skipper_skipper_data`), so every migration must be idempotent and ordered correctly. Two startup crashes came from getting this wrong (`a23c354`, and the v3.6.x chain).

## The pattern

Schema lives in two places that must stay consistent:

1. **`_CREATE_TABLES`** (executescript with `IF NOT EXISTS`) — defines the schema for a **fresh** database.
2. **Migration block in `init_db()`** — upgrades an **existing** database to match.

A new column/table must be added to BOTH: `_CREATE_TABLES` alone leaves prod broken (its `CREATE TABLE IF NOT EXISTS` is a no-op on existing tables); the migration alone leaves fresh installs broken.

## Adding a column

```python
cursor = await db.execute("PRAGMA table_info(<table>)")
columns = {row[1] for row in await cursor.fetchall()}
if "<new_col>" not in columns:
    await db.execute("ALTER TABLE <table> ADD COLUMN <new_col> <TYPE> DEFAULT <value>")
```

- A `NOT NULL` column MUST have a `DEFAULT` — SQLite rejects the ALTER otherwise.
- Re-check `PRAGMA table_info` per migration step (earlier steps may have rebuilt the table).

## Ordering trap: indexes on migrated columns

An index that references a column added by a migration must NOT go into `_CREATE_TABLES` — on an existing DB the executescript runs **before** the migration block, the column doesn't exist yet, and startup crashes (commit `a23c354`). Such indexes go **after** the migration block, with `IF NOT EXISTS`:

```python
# Indexes that depend on columns added above must run after migrations
await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS ... ON ...")
```

(See the existing comment at that spot in `init_db()` — keep new ones below it.)

## Changes ALTER can't do (drop a UNIQUE, change a PK)

Use the table-rebuild pattern (template: the `track_aliases` migration in `init_db()`):

```sql
CREATE TABLE <t>_new (...);            -- new shape
INSERT INTO <t>_new (...) SELECT ... FROM <t>;
DROP TABLE <t>;
ALTER TABLE <t>_new RENAME TO <t>;
```

Guard it with a `PRAGMA table_info` check so it only runs once. Remember the rebuild drops all indexes on the old table — recreate them (after the migration block, per the ordering trap).

## Upsert + partial unique index trap

`ON CONFLICT(col)` against a **partial** unique index must repeat the index's `WHERE` clause, or SQLite won't match the index and the insert fails (commit `c1f4c08`):

```sql
INSERT INTO track_aliases (...) VALUES (...)
ON CONFLICT(track_id) WHERE track_id IS NOT NULL DO UPDATE SET ...
```

Copy `add_track_alias` when upserting against a partial index.

## Rules

- **Idempotent, always.** Every step guarded by `PRAGMA table_info` / `IF NOT EXISTS` / `INSERT OR IGNORE` — init_db re-runs on every deploy and every container restart.
- **Never destructive without a data path.** If a migration drops/rebuilds a table, the `INSERT ... SELECT` must carry all existing rows; if data is intentionally discarded (like the old `mapping_fail_dismissals`), say so in a comment and consider a back-fill (see the alias back-fill at the end of `init_db()`).
- **Verify both paths before releasing:** (a) fresh DB — delete the local dev DB and start; (b) migrated DB — start against a copy of a pre-change DB. Prod has Hetzner daily backups, but a startup crash still takes the app down until rolled back.
- DELETE statements follow the CLAUDE.md transaction rule (BEGIN, check rowcount, COMMIT/ROLLBACK).
