"""Shared durable storage helpers for the productivity tools (P1.1).

Each productivity store keeps its in-memory dict as a working cache and
persists every mutation to the canonical SQLite database immediately, so
personal state (notes, tasks, contacts, events, reminders) survives restarts.
Caches are rebuilt from disk on construction; a single corrupt row is skipped
(best-effort recovery) rather than aborting the whole reload.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from app.db import SQLiteJsonTable, resolve_database_path

log = logging.getLogger(__name__)


def open_table(table: str, db_path: str | None = None) -> SQLiteJsonTable:
    """Open the durable JSON table for ``table`` at the canonical DB path."""
    return SQLiteJsonTable(db_path or resolve_database_path(), table)


def rebuild(entities: dict[str, Any], db: SQLiteJsonTable, from_dict: Callable[[dict], Any]) -> None:
    """Rebuild an in-memory cache from durable rows, skipping corrupt rows."""
    for payload in db.all():
        try:
            entity = from_dict(payload)
        except Exception as exc:  # noqa: BLE001 - tolerate one bad row
            log.warning("%s: skipping corrupt row %s: %s", db.table, payload.get("id"), exc)
            continue
        entities[entity.id] = entity


def save(db: SQLiteJsonTable, entity: Any) -> None:
    """Persist ``entity`` (must expose ``id`` and ``to_dict``)."""
    db.put(entity.id, entity.to_dict())


def delete_row(db: SQLiteJsonTable, entity_id: str) -> bool:
    return db.delete(entity_id)
