"""Phase 10.1 — Lightweight Session Index.

A small, deterministic index whose only job is locating relevant sessions. Each
entry stores metadata only (SessionMetadata) — never conversations, never
memories, never duplicates of session content.
"""

from __future__ import annotations

from pathlib import Path

from app.memory.session_models import SessionMetadata
from app.memory.session_store import SESSION_INDEX_FILENAME, read_json, write_json


class SessionIndex:
    """Metadata-only index over the sessions stored under a base directory."""

    def __init__(self, base_dir: str | Path) -> None:
        self._path = Path(base_dir) / SESSION_INDEX_FILENAME
        self._entries: dict[str, SessionMetadata] = {}
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> None:
        raw = read_json(self._path) or {}
        for session_id, data in raw.items():
            if not isinstance(data, dict):
                continue
            try:
                self._entries[session_id] = SessionMetadata(**data)
            except Exception:
                continue

    def save(self) -> None:
        """Persist the index as a JSON object keyed by session_id."""
        write_json(self._path, {
            session_id: entry.model_dump()
            for session_id, entry in sorted(self._entries.items())
        })

    def contains(self, session_id: str) -> bool:
        return session_id in self._entries

    def get(self, session_id: str) -> SessionMetadata | None:
        return self._entries.get(session_id)

    def upsert(self, metadata: SessionMetadata) -> None:
        self._entries[metadata.session_id] = metadata
        self.save()

    def remove(self, session_id: str) -> bool:
        removed = session_id in self._entries
        if removed:
            del self._entries[session_id]
            self.save()
        return removed

    def clear(self) -> None:
        self._entries.clear()
        self.save()

    def list_entries(self) -> list[SessionMetadata]:
        """All index entries, deterministically ordered (newest updated first)."""
        return sorted(
            self._entries.values(),
            key=lambda entry: (entry.updated_at, entry.session_id),
            reverse=True,
        )

    def __len__(self) -> int:
        return len(self._entries)
