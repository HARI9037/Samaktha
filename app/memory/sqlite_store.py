import sqlite3
from datetime import datetime
from threading import Lock
from typing import Iterator, Optional

from app.memory.models import MemoryEntry

_DB_PATH = 'data/memory.db'
_TABLE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS memory_entries (
    id TEXT PRIMARY KEY,
    key TEXT UNIQUE,
    value TEXT,
    category TEXT,
    created_at TEXT,
    updated_at TEXT
)
'''

class SQLiteStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or _DB_PATH
        self._lock = Lock()
        self._ensure_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_db(self):
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(_TABLE_SCHEMA)
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
        )
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """
                    INSERT INTO memory_entries (id, key, value, category, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value=excluded.value,
                        category=excluded.category,
                        updated_at=excluded.updated_at
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
            created_at=datetime.fromisoformat(row['created_at']),
            updated_at=datetime.fromisoformat(row['updated_at']),
        )
