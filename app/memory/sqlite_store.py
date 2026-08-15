import json
import sqlite3
from datetime import datetime
from threading import Lock
from typing import Optional

from app.db.base import ensure_table
from app.db.config import connect, resolve_database_path
from app.memory.models import MemoryEntry
from app.memory.time_utils import normalize_datetime

_TABLE_NAME = "memory_entries"
_SCHEMA_VERSION = 1

_TABLE_COLUMNS = [
    ("id", "TEXT PRIMARY KEY"),
    ("key", "TEXT UNIQUE"),
    ("value", "TEXT"),
    ("category", "TEXT"),
    ("created_at", "TEXT"),
    ("updated_at", "TEXT"),
    ("metadata", "TEXT DEFAULT '{}'"),
    ("score", "REAL DEFAULT 0"),
]


class SQLiteStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or resolve_database_path()
        self._lock = Lock()
        self._ensure_db()

    def _get_conn(self):
        return connect(self.db_path)

    def _ensure_db(self):
        with self._lock:
            conn = self._get_conn()
            try:
                ensure_table(conn, _TABLE_NAME, _TABLE_COLUMNS, _SCHEMA_VERSION)
                conn.commit()
            finally:
                conn.close()

    def store_entry(self, entry: MemoryEntry) -> None:
        data = (
            entry.id,
            entry.key,
            str(entry.value),
            entry.category,
            entry.created_at.isoformat(),
            entry.updated_at.isoformat(),
            json.dumps(entry.metadata),
            entry.score,
        )
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """
                    INSERT INTO memory_entries (id, key, value, category, created_at, updated_at, metadata, score) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value=excluded.value,
                        category=excluded.category,
                        updated_at=excluded.updated_at,
                        metadata=excluded.metadata,
                        score=excluded.score
                    """,
                    data,
                )
                conn.commit()
            finally:
                conn.close()

    def retrieve_entry(self, key: str) -> Optional[MemoryEntry]:
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute('SELECT * FROM memory_entries WHERE key=?', (key,)).fetchone()
                if row:
                    return self._row_to_entry(row)
                return None
            finally:
                conn.close()

    def delete_entry(self, key: str) -> None:
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute('DELETE FROM memory_entries WHERE key=?', (key,))
                conn.commit()
            finally:
                conn.close()

    def list_entries(self) -> list[MemoryEntry]:
        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute('SELECT * FROM memory_entries').fetchall()
                return [self._row_to_entry(row) for row in rows]
            finally:
                conn.close()

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> MemoryEntry:
        return MemoryEntry(
            id=row['id'],
            key=row['key'],
            value=row['value'],
            category=row['category'],
            created_at=normalize_datetime(row['created_at']) or datetime.fromisoformat(row['created_at']),
            updated_at=normalize_datetime(row['updated_at']) or datetime.fromisoformat(row['updated_at']),
            metadata=json.loads(row['metadata'] or '{}'),
            score=float(row['score'] or 0),
        )
