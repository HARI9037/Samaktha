"""Shared SQLite schema, versioning, and generic JSON-table store (P1.3).

Versioning strategy
-------------------
Every table belongs to a logical schema stamped with ``PRAGMA user_version``.
Migrations are additive and idempotent: a store declares its full current
column list and the schema version at which it was introduced;
:func:`ensure_table` creates the table when missing and adds any missing
columns to an older table (a monotonic upgrade). Versions never decrease and
downgrades are never performed. Existing data is never dropped.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from typing import Any, Optional

from app.db.config import connect

log = logging.getLogger(__name__)

DEFAULT_SCHEMA_VERSION = 1


def get_user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def set_user_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(f"PRAGMA user_version = {int(version)}")


def existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_table(
    conn: sqlite3.Connection,
    table: str,
    columns: list[tuple[str, str]],
    version: int = DEFAULT_SCHEMA_VERSION,
) -> None:
    """Create ``table`` if missing and add any missing columns idempotently.

    ``columns`` is the full current schema as ``(name, sql_type)`` pairs. A
    pre-existing table is upgraded by adding only the columns it lacks, then
    ``PRAGMA user_version`` is stamped with ``max(current, version)``.
    """
    col_defs = ", ".join(f"{name} {ddl}" for name, ddl in columns)
    conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({col_defs})")
    existing = existing_columns(conn, table)
    for name, ddl in columns:
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    current = get_user_version(conn)
    if current < version:
        set_user_version(conn, version)


class SQLiteJsonTable:
    """Generic durable table storing arbitrary JSON payloads by id.

    Row layout: ``id TEXT PRIMARY KEY``, ``data TEXT NOT NULL`` (JSON), plus
    ``created_at`` / ``updated_at`` ISO-8601 timestamps. Payload
    serialization/deserialization happens here; callers only deal with dicts.

    Each instance guards mutations with its own lock, so multiple store
    instances over the same file stay safe within one process; across
    processes/instances WAL + busy_timeout handle contention.
    """

    def __init__(self, db_path: str, table: str, version: int = DEFAULT_SCHEMA_VERSION):
        self.db_path = db_path
        self.table = table
        self._version = version
        self._lock = threading.Lock()
        conn = connect(db_path)
        try:
            ensure_table(conn, table, self._columns(), version)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _columns() -> list[tuple[str, str]]:
        return [
            ("id", "TEXT PRIMARY KEY"),
            ("data", "TEXT NOT NULL"),
            ("created_at", "TEXT"),
            ("updated_at", "TEXT"),
        ]

    def put(
        self,
        record_id: str,
        payload: dict[str, Any],
        *,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
    ) -> None:
        with self._lock:
            conn = connect(self.db_path)
            try:
                conn.execute(
                    f"INSERT INTO {self.table} (id, data, created_at, updated_at) "
                    f"VALUES (?, ?, ?, ?) "
                    f"ON CONFLICT(id) DO UPDATE SET "
                    f"data=excluded.data, updated_at=excluded.updated_at",
                    (record_id, json.dumps(payload, ensure_ascii=False), created_at, updated_at),
                )
                conn.commit()
            finally:
                conn.close()

    def get(self, record_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            conn = connect(self.db_path)
            try:
                row = conn.execute(
                    f"SELECT data FROM {self.table} WHERE id = ?", (record_id,)
                ).fetchone()
                if not row:
                    return None
                try:
                    return json.loads(row["data"])
                except (ValueError, TypeError) as exc:
                    log.warning("%s: corrupt row %r skipped: %s", self.table, record_id, exc)
                    return None
            finally:
                conn.close()

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            conn = connect(self.db_path)
            try:
                rows = conn.execute(f"SELECT data FROM {self.table} ORDER BY id").fetchall()
                results: list[dict[str, Any]] = []
                for row in rows:
                    try:
                        results.append(json.loads(row["data"]))
                    except (ValueError, TypeError) as exc:
                        log.warning("%s: corrupt row skipped: %s", self.table, exc)
                return results
            finally:
                conn.close()

    def delete(self, record_id: str) -> bool:
        with self._lock:
            conn = connect(self.db_path)
            try:
                cur = conn.execute(f"DELETE FROM {self.table} WHERE id = ?", (record_id,))
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def count(self) -> int:
        with self._lock:
            conn = connect(self.db_path)
            try:
                row = conn.execute(f"SELECT COUNT(*) AS n FROM {self.table}").fetchone()
                return int(row["n"])
            finally:
                conn.close()

    def clear(self) -> None:
        with self._lock:
            conn = connect(self.db_path)
            try:
                conn.execute(f"DELETE FROM {self.table}")
                conn.commit()
            finally:
                conn.close()
