"""Phase 15 — Communication delivery history (audit trail).

Stores deterministic delivery history. When ``db_path`` is supplied the
history is a durable audit trail persisted via the shared SQLite JSON store;
otherwise it is in-memory only. Entry count is bounded by ``max_entries`` in
both memory and durable storage (oldest dropped first).
"""

from __future__ import annotations

import logging
from typing import Optional

from app.communication.models import CommunicationHistoryEntry
from app.db.base import SQLiteJsonTable

log = logging.getLogger(__name__)


class CommunicationHistory:
    """Stores deterministic delivery history (audit trail)."""

    def __init__(self, max_entries: int = 1000, db_path: Optional[str] = None) -> None:
        self._entries: list[CommunicationHistoryEntry] = []
        self._row_ids: list[str] = []
        self._max_entries = max_entries
        self._seq = 0
        self._store: SQLiteJsonTable | None = None
        if db_path:
            self._store = SQLiteJsonTable(db_path, "communication_history")
            self._restore()

    def _restore(self) -> None:
        for payload in self._store.all():
            row_id = str(payload.pop("_row_id", ""))
            try:
                entry = CommunicationHistoryEntry.model_validate(payload)
            except Exception as exc:
                log.warning("Skipping corrupt communication history row %r: %s", row_id, exc)
                continue
            if not row_id.startswith("audit-"):
                row_id = ""
            self._entries.append(entry)
            self._row_ids.append(row_id)
        while len(self._entries) > self._max_entries:
            self._entries.pop(0)
            self._row_ids.pop(0)

    def add_entry(self, entry: CommunicationHistoryEntry) -> None:
        self._seq += 1
        row_id = f"audit-{self._seq}"
        if self._store:
            payload = entry.model_dump(mode="json")
            payload["_row_id"] = row_id
            try:
                self._store.put(row_id, payload)
            except Exception as exc:
                log.error("Failed to persist communication history entry: %s", exc)
        self._entries.append(entry)
        self._row_ids.append(row_id)
        if len(self._entries) > self._max_entries:
            old_row = self._row_ids.pop(0)
            self._entries.pop(0)
            if self._store and old_row:
                try:
                    self._store.delete(old_row)
                except Exception as exc:
                    log.error("Failed to prune communication history row: %s", exc)

    def get_entries(self, limit: int = 100) -> list[CommunicationHistoryEntry]:
        return self._entries[-limit:]

    def get_entries_by_recipient(self, recipient: str) -> list[CommunicationHistoryEntry]:
        return [e for e in self._entries if e.recipient == recipient]

    def get_entries_by_provider(self, provider: str) -> list[CommunicationHistoryEntry]:
        return [e for e in self._entries if e.provider.value == provider]

    def get_entries_by_status(self, status: str) -> list[CommunicationHistoryEntry]:
        return [e for e in self._entries if e.status.value == status]

    def search(self, query: str) -> list[CommunicationHistoryEntry]:
        query_lower = query.lower()
        results = []
        for entry in self._entries:
            if query_lower in entry.recipient.lower():
                results.append(entry)
            elif query_lower in entry.subject.lower():
                results.append(entry)
            elif query_lower in entry.delivery_status.lower():
                results.append(entry)
        return results

    def clear(self) -> None:
        self._entries.clear()
        self._row_ids.clear()
        if self._store:
            try:
                self._store.clear()
            except Exception as exc:
                log.error("Failed to clear durable communication history: %s", exc)

    def count(self) -> int:
        return len(self._entries)

    def durable(self) -> bool:
        return self._store is not None

    def get_last_entry(self) -> CommunicationHistoryEntry | None:
        if self._entries:
            return self._entries[-1]
        return None
