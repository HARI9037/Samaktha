"""P1.3 — SQLite reliability regression tests.

Covers the P1.3 checklist:
- WAL journal mode + busy_timeout configured on every connection.
- Database path centralized (settings.sqlite_url is the single source; no
  hardcoded data/memory.db defaults left in stores or diagnostics).
- Versioned, additive schema migrations (PRAGMA user_version).
- Concurrent writes across store instances do not raise SQLITE_BUSY or lose
  data (WAL + busy_timeout).
- Restart persistence: data written by one store instance is readable by a
  fresh instance over the same file.
- Generic JSON-table store used by the productivity layer.
"""

import sqlite3
import threading

import pytest

from app.config.settings import Settings
from app.db import SQLiteJsonTable, connect, get_user_version, resolve_database_path
from app.db.base import ensure_table
from app.diagnostics import SystemDiagnostics
from app.memory.models import MemoryEntry
from app.memory.sqlite_store import SQLiteStore


@pytest.fixture
def settings_with_tmp_db(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'canonical.db'}"
    settings = Settings(sqlite_url=url)
    monkeypatch.setattr("app.db.config.get_settings", lambda: settings)
    return settings


def test_connections_use_wal_and_busy_timeout(tmp_path):
    conn = connect(str(tmp_path / "reliability.db"))
    try:
        assert conn.row_factory is sqlite3.Row
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        conn.close()


def test_default_store_path_comes_from_settings(settings_with_tmp_db):
    store = SQLiteStore()
    assert store.db_path == settings_with_tmp_db.sqlite_url.removeprefix("sqlite:///")
    assert store.db_path.endswith("canonical.db")


def test_resolve_database_path_uses_settings(settings_with_tmp_db):
    assert resolve_database_path() == str(settings_with_tmp_db.sqlite_url.removeprefix("sqlite:///"))


def test_schema_version_stamped_after_ensure(tmp_path):
    SQLiteStore(db_path=str(tmp_path / "v.db"))
    conn = connect(str(tmp_path / "v.db"))
    try:
        assert get_user_version(conn) == 1
    finally:
        conn.close()


def test_ensure_table_idempotent(tmp_path):
    path = str(tmp_path / "idem.db")
    conn = connect(path)
    try:
        ensure_table(conn, "t", [("id", "TEXT PRIMARY KEY"), ("data", "TEXT NOT NULL")], version=1)
        ensure_table(conn, "t", [("id", "TEXT PRIMARY KEY"), ("data", "TEXT NOT NULL")], version=1)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(t)").fetchall()}
        assert columns == {"id", "data"}
        assert get_user_version(conn) == 1
    finally:
        conn.close()


def test_legacy_table_upgraded_with_missing_columns(tmp_path):
    path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE memory_entries (id TEXT PRIMARY KEY, key TEXT UNIQUE)")
        conn.commit()
    finally:
        conn.close()

    store = SQLiteStore(db_path=path)
    entries = store.list_entries()
    assert entries == []
    conn = connect(path)
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(memory_entries)").fetchall()}
        assert {"value", "category", "created_at", "updated_at", "metadata", "score"} <= columns
        assert get_user_version(conn) == 1
    finally:
        conn.close()


def _entry(record_id: str, key: str, value: str) -> MemoryEntry:
    return MemoryEntry(
        id=record_id,
        key=key,
        value=value,
        category="test",
        created_at=memory_aware_now(),
        updated_at=memory_aware_now(),
        metadata={},
        score=1.0,
    )


def memory_aware_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def test_concurrent_writes_across_instances(tmp_path):
    path = str(tmp_path / "concurrent.db")
    stores = [SQLiteStore(db_path=path) for _ in range(2)]
    errors: list[Exception] = []

    def worker(store, start: int, count: int):
        try:
            for i in range(count):
                n = start + i
                store.store_entry(_entry(f"id-{n}", f"key-{n}", f"value-{n}"))
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(stores[0], 0, 50)),
        threading.Thread(target=worker, args=(stores[1], 50, 50)),
        threading.Thread(target=worker, args=(stores[0], 100, 50)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(stores[0].list_entries()) == 150
    assert len(stores[1].list_entries()) == 150


def test_restart_persistence(tmp_path):
    path = str(tmp_path / "restart.db")
    first = SQLiteStore(db_path=path)
    first.store_entry(_entry("id-1", "persisted", "still here"))

    second = SQLiteStore(db_path=path)
    record = second.retrieve_entry("persisted")
    assert record is not None
    assert record.value == "still here"


def test_json_table_roundtrip(tmp_path):
    table = SQLiteJsonTable(str(tmp_path / "json.db"), "notes")
    table.put("n1", {"title": "Groceries", "body": "Milk"})
    table.put("n1", {"title": "Groceries", "body": "Milk and eggs"})
    assert table.count() == 1
    assert table.get("n1") == {"title": "Groceries", "body": "Milk and eggs"}
    assert table.get("missing") is None
    table.put("n2", {"title": "Second"})
    assert {row["title"] for row in table.all()} == {"Groceries", "Second"}
    assert table.delete("n1") is True
    assert table.delete("n1") is False
    assert table.count() == 1
    table.clear()
    assert table.count() == 0


def test_json_table_survives_new_instance(tmp_path):
    path = str(tmp_path / "json_restart.db")
    SQLiteJsonTable(path, "tasks").put("t1", {"title": "Ship P1"})
    fresh = SQLiteJsonTable(path, "tasks")
    assert fresh.get("t1") == {"title": "Ship P1"}


def test_diagnostics_uses_settings_path(settings_with_tmp_db):
    checks = SystemDiagnostics()._memory_checks()
    sqlite_check = next(c for c in checks if c.label == "SQLite")
    assert sqlite_check.detail == settings_with_tmp_db.sqlite_url.removeprefix("sqlite:///")


def test_sqlite_store_module_has_no_hardcoded_default_path():
    import inspect

    import app.memory.sqlite_store as module

    source = inspect.getsource(module)
    assert "data/memory.db" not in source
    assert "_DB_PATH" not in source
