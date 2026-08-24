"""Phase 10.1 — Deterministic Session Memory Manager.

Every conversation belongs to exactly one Session. This manager creates,
loads, saves, updates, lists, and deletes sessions and their temporary session
memory, keeping the Session Index in sync. No learning, no retrieval scoring,
no embeddings, no vector search.

Forgetting is deterministic: deleting a session removes its folder, its index
entry, and its cache entry. ``delete_everything`` additionally requests
long-term memory deletion through the Memory Controller so no orphaned
metadata is left behind.

Phase 20.2.2 hardening
-----------------------
- Thread-safe writes via ``threading.Lock`` (one lock per manager instance).
- Schema migration on ``load_session`` (older sessions upgraded to current).
- Corrupted-file recovery: returns best-effort session and emits a warning.
- Duplicate history protection: ``append_history`` skips duplicate event IDs.
- Session rotation: configurable ``max_history_entries``; oldest entries are
  moved to a ``session_memory_archive.json`` sidecar, never deleted.
- Cache bounding (P1.4): configurable ``max_cached_sessions``; the
  least-recently-used sessions are evicted from the in-memory cache (never
  from disk), so memory growth is bounded while durability is unaffected.
- Atomic writes delegated to ``session_store.write_json`` /
  ``session_store.write_text_atomic``.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import warnings
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.memory.session_index import SessionIndex
from app.core.contracts.memory import DEFAULT_LOCAL_PRINCIPAL_ID
from app.memory.session_models import (
    Session,
    SessionHistoryEntry,
    SessionMemory,
    SessionMemoryEntry,
    SessionMetadata,
)
from app.memory.session_store import (
    DEFAULT_BASE_DIR,
    export_session_markdown,
    metadata_path,
    migrate_session_data,
    read_json,
    session_dir,
    session_memory_json_path,
    session_memory_md_path,
    sessions_dir,
    write_json,
    write_text_atomic,
)

log = logging.getLogger(__name__)

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Memory types the Memory Controller knows about (metadata_manager.MemoryType).
_LONG_TERM_MEMORY_TYPES = (
    "conversation",
    "document",
    "preference",
    "workflow",
    "tool",
    "knowledge",
    "system",
)

# Archive sidecar filename (alongside session_memory.json).
_ARCHIVE_FILENAME = "session_memory_archive.json"

# Default cap on sessions kept in the in-memory cache. Sessions are durable
# on disk, so eviction only forces a reload on next access (memory bounded,
# P1.4).
DEFAULT_MAX_CACHED_SESSIONS = 256


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionManager:
    """Deterministic session storage: create/load/save/update/delete/list.

    Thread safety
    -------------
    A single ``threading.Lock`` guards all mutating operations so that
    concurrent callers within the same process cannot corrupt history,
    metadata, or the markdown export.

    Rotation
    --------
    When ``max_history_entries`` is set and the history exceeds that limit,
    the oldest entries are **moved** (never deleted) to a sidecar archive
    file (``session_memory_archive.json``) before the session is written.
    """

    def __init__(
        self,
        base_dir: str | Path | None = None,
        memory_controller: Any | None = None,
        clock: Callable[[], str] = _utc_now,
        max_history_entries: int | None = None,
        max_cached_sessions: int | None = DEFAULT_MAX_CACHED_SESSIONS,
    ) -> None:
        self._base_dir = Path(base_dir or DEFAULT_BASE_DIR)
        self._memory_controller = memory_controller
        self._clock = clock
        self._max_history_entries = max_history_entries
        self._max_cached_sessions = max_cached_sessions
        self._index = SessionIndex(self._base_dir)
        self._cache: "OrderedDict[str, Session]" = OrderedDict()
        self._counter = 0
        self._lock = threading.Lock()  # Phase 20.2.2 — thread safety

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    @property
    def index(self) -> SessionIndex:
        return self._index

    def _now(self) -> str:
        return self._clock()

    # ------------------------------------------------------------------
    # Cache bounding (P1.4) — sessions are durable on disk, so eviction
    # only means the next access reloads from disk. Least-recently-used
    # sessions are evicted first.
    # ------------------------------------------------------------------

    def _cache_session(self, session_id: str, session: Session) -> None:
        self._cache[session_id] = session
        self._cache.move_to_end(session_id)
        self._bound_cache()

    def _bound_cache(self) -> None:
        if self._max_cached_sessions is None:
            return
        while len(self._cache) > self._max_cached_sessions:
            _, evicted = self._cache.popitem(last=False)
            log.debug(
                "SessionManager: evicted cached session %r (bound=%d)",
                evicted.session_id,
                self._max_cached_sessions,
            )

    def prune_cache(self) -> int:
        """Evict cached sessions beyond the bound; returns count removed."""
        with self._lock:
            before = len(self._cache)
            self._bound_cache()
            return before - len(self._cache)

    def _next_session_id(self, now: str) -> str:
        self._counter += 1
        return f"session-{re.sub(r'[^0-9]', '', now)[:14]}-{self._counter:04d}"

    # ------------------------------------------------------------------
    # Internal write (always called under self._lock)
    # ------------------------------------------------------------------

    def _write_session(self, session: Session) -> None:
        session.metadata.topic_summary = self._build_topic_summary(session)

        # Rotation — move oldest entries to archive before writing.
        if (
            self._max_history_entries is not None
            and len(session.memory.history) > self._max_history_entries
        ):
            self._rotate_history(session)

        folder = session_dir(self._base_dir, session.session_id)
        folder.mkdir(parents=True, exist_ok=True)

        write_json(
            metadata_path(self._base_dir, session.session_id),
            session.metadata.model_dump(),
        )
        write_json(
            session_memory_json_path(self._base_dir, session.session_id),
            session.memory.model_dump(),
        )
        write_text_atomic(
            session_memory_md_path(self._base_dir, session.session_id),
            export_session_markdown(session.metadata, session.memory),
        )
        self._index.upsert(session.metadata)

    def _rotate_history(self, session: Session) -> None:
        """Move overflow history to archive sidecar — never delete entries."""
        keep = self._max_history_entries or 0
        overflow = session.memory.history[:-keep] if keep > 0 else session.memory.history[:]
        session.memory.history = session.memory.history[-keep:] if keep > 0 else []

        archive_path = session_dir(self._base_dir, session.session_id) / _ARCHIVE_FILENAME
        existing: list[dict] = []
        try:
            if archive_path.exists():
                raw = read_json(archive_path)
                if isinstance(raw, list):
                    existing = raw
                else:
                    raise ValueError("archive is not a list")
        except Exception as exc:
            if archive_path.exists():
                log.warning("SessionManager: archive corrupt for %r: %s. Renaming to .bak", session.session_id, exc)
                try:
                    import os
                    bak_path = archive_path.with_suffix(".json.bak")
                    os.replace(archive_path, bak_path)
                except Exception:
                    pass
        existing.extend(e.model_dump() for e in overflow)
        write_json(archive_path, existing)
        log.info(
            "SessionManager: rotated %d history entries to archive for session %r",
            len(overflow),
            session.session_id,
        )

    # ------------------------------------------------------------------
    # Create / load / save
    # ------------------------------------------------------------------

    def create_session(
        self,
        *,
        session_id: str | None = None,
        title: str = "",
        tags: list[str] | None = None,
        projects: list[str] | None = None,
        principal_id: str = DEFAULT_LOCAL_PRINCIPAL_ID,
        workspace_id: str | None = None,
        profile_id: str | None = None,
    ) -> Session:
        """Create a new session and persist its folder and index entry."""
        with self._lock:
            now = self._now()
            resolved_id = session_id or self._next_session_id(now)
            if not _SESSION_ID_RE.match(resolved_id):
                raise ValueError(f"invalid session id: {resolved_id!r}")
            if self._index.contains(resolved_id):
                raise ValueError(f"session already exists: {resolved_id}")
            metadata = SessionMetadata(
                session_id=resolved_id,
                principal_id=principal_id,
                workspace_id=workspace_id,
                profile_id=profile_id,
                created_at=now,
                updated_at=now,
                title=title,
                tags=tags or [],
                projects=projects or [],
            )
            memory = SessionMemory(session_id=resolved_id)
            session = Session(metadata=metadata, memory=memory)
            session.metadata.topic_summary = self._build_topic_summary(session)
            self._write_session(session)
            self._cache_session(resolved_id, session)
            return session

    def session_exists(self, session_id: str) -> bool:
        return self._index.contains(session_id)

    def load_session(
        self,
        session_id: str,
        *,
        principal_id: str = DEFAULT_LOCAL_PRINCIPAL_ID,
    ) -> Session:
        """Load a session from its folder (cached). Reads JSON only.

        Phase 20.2.2: applies schema migration on every load so old sessions
        are automatically upgraded. If a file is corrupted, returns the best
        recoverable data and emits a warning — never raises on a partial read.
        """
        with self._lock:
            session = self._load_session_locked(session_id)
            self._assert_owner(session, principal_id)
            return session

    @staticmethod
    def _assert_owner(session: Session, principal_id: str) -> None:
        if session.metadata.principal_id != principal_id:
            raise PermissionError("session is not owned by the requesting principal")

    def resolve_session(
        self,
        session_id: str | None,
        *,
        principal_id: str = DEFAULT_LOCAL_PRINCIPAL_ID,
        create_if_missing: bool = True,
    ) -> Session:
        """Resolve an owned session; never create an unknown explicit ID."""

        if session_id:
            if not self.session_exists(session_id):
                raise KeyError(f"session not found: {session_id}")
            return self.load_session(session_id, principal_id=principal_id)
        if not create_if_missing:
            raise KeyError("session id is required")
        return self.create_session(principal_id=principal_id)

    def _load_session_locked(self, session_id: str) -> Session:
        """Internal load (must be called under self._lock)."""
        if session_id in self._cache:
            self._cache.move_to_end(session_id)
            return self._cache[session_id]
        if not self._index.contains(session_id):
            raise KeyError(f"session not found: {session_id}")

        meta_raw = None
        try:
            meta_raw = read_json(metadata_path(self._base_dir, session_id))
        except Exception as e:
            log.warning("SessionManager: error reading metadata for %r: %s", session_id, e)

        mem_raw = None
        try:
            mem_raw = read_json(session_memory_json_path(self._base_dir, session_id))
        except Exception as e:
            log.warning("SessionManager: error reading memory for %r: %s", session_id, e)

        # Recovery path — build safe defaults when files are missing/corrupt.
        now = _utc_now()
        if meta_raw is None or not isinstance(meta_raw, dict):
            warnings.warn(
                f"SessionManager: metadata.json for {session_id!r} is missing or corrupt; "
                "using deterministic defaults.",
                category=UserWarning,
                stacklevel=3,
            )
            meta_raw = {"session_id": session_id, "created_at": now, "updated_at": now}

        if mem_raw is None or not isinstance(mem_raw, dict):
            warnings.warn(
                f"SessionManager: session_memory.json for {session_id!r} is missing or corrupt; "
                "using empty memory.",
                category=UserWarning,
                stacklevel=3,
            )
            mem_raw = {"session_id": session_id}

        # Schema migration — applies deterministic defaults for missing fields.
        meta_raw = migrate_session_data(meta_raw, kind="metadata")
        mem_raw = migrate_session_data(mem_raw, kind="memory")

        try:
            metadata = SessionMetadata(**meta_raw)
        except Exception as exc:
            from pydantic import ValidationError
            warnings.warn(
                f"SessionManager: could not parse metadata for {session_id!r}: {exc}; "
                "recovering valid fields.",
                category=UserWarning,
                stacklevel=3,
            )
            if isinstance(exc, ValidationError):
                invalid_fields = {err.get("loc", (None,))[0] for err in exc.errors()}
                for f in invalid_fields:
                    if isinstance(f, str):
                        meta_raw.pop(f, None)
            else:
                meta_raw = {}
            meta_raw["session_id"] = session_id
            if "created_at" not in meta_raw: meta_raw["created_at"] = now
            if "updated_at" not in meta_raw: meta_raw["updated_at"] = now
            try:
                metadata = SessionMetadata(**meta_raw)
            except Exception:
                metadata = SessionMetadata(session_id=session_id, created_at=now, updated_at=now)

        try:
            memory = SessionMemory(**mem_raw)
        except Exception as exc:
            from pydantic import ValidationError
            warnings.warn(
                f"SessionManager: could not parse memory for {session_id!r}: {exc}; "
                "recovering valid fields.",
                category=UserWarning,
                stacklevel=3,
            )
            if isinstance(exc, ValidationError):
                invalid_fields = {err.get("loc", (None,))[0] for err in exc.errors()}
                for f in invalid_fields:
                    if isinstance(f, str):
                        mem_raw.pop(f, None)
            else:
                mem_raw = {}
            mem_raw["session_id"] = session_id
            try:
                memory = SessionMemory(**mem_raw)
            except Exception:
                memory = SessionMemory(session_id=session_id)

        session = Session(metadata=metadata, memory=memory)
        self._cache_session(session_id, session)
        return session

    def save_session(self, session: Session) -> None:
        """Persist a session (JSON + markdown export + index entry)."""
        with self._lock:
            session.metadata.updated_at = self._now()
            self._write_session(session)
            self._cache_session(session.session_id, session)

    # ------------------------------------------------------------------
    # Metadata updates
    # ------------------------------------------------------------------

    def update_metadata(
        self,
        session_id: str,
        new_metadata: SessionMetadata | None = None,
        *,
        title: str | None = None,
        summary: str | None = None,
        tags: list[str] | None = None,
        projects: list[str] | None = None,
        message_count: int | None = None,
    ) -> SessionMetadata:
        """Replace or selectively update session metadata.

        When ``new_metadata`` is supplied (Phase 20.2 SessionBuilder path), it
        replaces the stored metadata wholesale. Keyword arguments are then
        applied on top as overrides. This keeps the method a pure storage
        operation — no extraction logic.
        """
        with self._lock:
            session = self._load_session_locked(session_id)
            if new_metadata is not None:
                session.metadata = new_metadata
            if title is not None:
                session.metadata.title = title
            if summary is not None:
                session.metadata.summary = summary
            if tags is not None:
                session.metadata.tags = list(tags)
            if projects is not None:
                session.metadata.projects = list(projects)
            if message_count is not None:
                session.metadata.message_count = message_count
            session.metadata.updated_at = self._now()
            session.metadata.topic_summary = self._build_topic_summary(session)
            self._write_session(session)
            self._cache_session(session_id, session)
            return session.metadata

    # ------------------------------------------------------------------
    # Session history (event log — Phase 20.2)
    # ------------------------------------------------------------------

    def append_history(self, session_id: str, entry: SessionHistoryEntry) -> None:
        """Append one event to the session history log.

        Phase 20.2.1: assigns the next monotonic ``turn_number`` from
        ``session.memory.next_turn_number`` and then increments it. The
        counter is persisted in JSON so it survives cache eviction.

        Phase 20.2.2: duplicate event IDs are silently skipped, ensuring
        idempotent replay and retry safety.

        Pure storage: no classification, no extraction, no synthesis.
        """
        with self._lock:
            session = self._load_session_locked(session_id)

            # Duplicate protection — skip if event ID already in history.
            existing_ids = {e.id for e in session.memory.history}
            if entry.id in existing_ids:
                log.debug(
                    "SessionManager: skipping duplicate history entry %r for session %r",
                    entry.id,
                    session_id,
                )
                return

            # Stamp with the next monotonic turn number.
            entry = entry.model_copy(update={"turn_number": session.memory.next_turn_number})
            session.memory.next_turn_number += 1
            session.memory.history.append(entry)
            session.metadata.updated_at = self._now()
            self._write_session(session)
            self._cache_session(session_id, session)

    def load_archived_history(self, session_id: str) -> list[SessionHistoryEntry]:
        """Return rotated history entries from the archive sidecar, if any."""
        archive_path = session_dir(self._base_dir, session_id) / _ARCHIVE_FILENAME
        raw = read_json(archive_path)
        if not isinstance(raw, list):
            return []
        entries: list[SessionHistoryEntry] = []
        for item in raw:
            try:
                entries.append(SessionHistoryEntry(**item))
            except Exception:
                pass
        return entries

    # ------------------------------------------------------------------
    # Session memory (temporary facts)
    # ------------------------------------------------------------------

    def get_session_memory(self, session_id: str) -> SessionMemory:
        return self.load_session(session_id).memory

    def store_fact(
        self,
        session_id: str,
        key: str,
        value: str,
        category: str = "fact",
    ) -> SessionMemoryEntry:
        """Alias for add_memory_entry with Phase 20.2 naming."""
        return self.add_memory_entry(session_id, key, value, category)

    def add_memory_entry(
        self,
        session_id: str,
        key: str,
        value: str,
        category: str = "fact",
    ) -> SessionMemoryEntry:
        """Deterministic upsert of one temporary fact (updates by key)."""
        with self._lock:
            session = self._load_session_locked(session_id)
            now = self._now()
            entry: SessionMemoryEntry | None = None
            for index, existing in enumerate(session.memory.entries):
                if existing.key == key:
                    entry = SessionMemoryEntry(
                        key=key,
                        value=value,
                        category=category,
                        created_at=existing.created_at,
                        updated_at=now,
                    )
                    session.memory.entries[index] = entry
                    break
            if entry is None:
                entry = SessionMemoryEntry(
                    key=key,
                    value=value,
                    category=category,
                    created_at=now,
                    updated_at=now,
                )
                session.memory.entries.append(entry)
            session.metadata.updated_at = now
            session.metadata.topic_summary = self._build_topic_summary(session)
            self._write_session(session)
            self._cache_session(session_id, session)
            return entry

    # ------------------------------------------------------------------
    # Listing / forgetting
    # ------------------------------------------------------------------

    def list_sessions(
        self,
        *,
        principal_id: str = DEFAULT_LOCAL_PRINCIPAL_ID,
    ) -> list[SessionMetadata]:
        """Index metadata owned by one principal (never session content)."""
        return [
            metadata for metadata in self._index.list_entries()
            if metadata.principal_id == principal_id
        ]

    def delete_session(
        self,
        session_id: str,
        *,
        principal_id: str = DEFAULT_LOCAL_PRINCIPAL_ID,
    ) -> bool:
        """Deterministic deletion: folder + index entry + cache entry."""
        with self._lock:
            if not self._index.contains(session_id):
                return False
            metadata = self._index.get(session_id)
            if metadata is None or metadata.principal_id != principal_id:
                return False
            folder = session_dir(self._base_dir, session_id)
            if folder.exists():
                shutil.rmtree(folder)
            self._index.remove(session_id)
            self._cache.pop(session_id, None)
            return True

    def delete_everything(self) -> None:
        """Remove all session folders, clear the index, and clear caches.

        Also requests long-term memory deletion through the Memory Controller
        so no orphaned metadata is left behind.
        """
        with self._lock:
            directory = sessions_dir(self._base_dir)
            if directory.exists():
                shutil.rmtree(directory)
            self._index.clear()
            self._cache.clear()
        self._request_long_term_memory_deletion()

    def _request_long_term_memory_deletion(self) -> None:
        controller = self._memory_controller
        if controller is None:
            return
        delete_by_type = getattr(controller, "delete_by_type", None)
        if callable(delete_by_type):
            for memory_type in _LONG_TERM_MEMORY_TYPES:
                delete_by_type(memory_type)
        clear_cache = getattr(controller, "clear_cache", None)
        if callable(clear_cache):
            clear_cache()

    @staticmethod
    def _build_topic_summary(session: Session) -> list[str]:
        topics: list[str] = []
        if session.metadata.title:
            topics.append(session.metadata.title)
        if session.metadata.summary:
            topics.extend(
                [part.strip() for part in session.metadata.summary.split("•") if part.strip()]
            )
        for entry in session.memory.entries[:5]:
            label = entry.key.strip()
            if label:
                topics.append(f"{entry.category}: {label}")
        # Include tools used from structured metadata (not from history scanning).
        for tool in session.metadata.tools_used[:3]:
            if tool:
                topics.append(f"tool: {tool}")
        deduped: list[str] = []
        seen: set[str] = set()
        for topic in topics:
            key = topic.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(topic)
        return deduped[:8]
