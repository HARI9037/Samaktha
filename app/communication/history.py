"""Phase 15 — Communication delivery history.

Stores deterministic delivery history.
Integrates with Memory later.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.communication.models import CommunicationHistoryEntry

log = logging.getLogger(__name__)


class CommunicationHistory:
    """Stores deterministic delivery history."""

    def __init__(self, max_entries: int = 1000) -> None:
        self._entries: list[CommunicationHistoryEntry] = []
        self._max_entries = max_entries

    def add_entry(self, entry: CommunicationHistoryEntry) -> None:
        self._entries.append(entry)
        if len(self._entries) > self._max_entries:
            self._entries.pop(0)

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

    def count(self) -> int:
        return len(self._entries)

    def get_last_entry(self) -> CommunicationHistoryEntry | None:
        if self._entries:
            return self._entries[-1]
        return None