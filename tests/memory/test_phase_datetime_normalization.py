from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.core.contracts.memory import MemoryItem, MemoryType
from app.memory.context import ContextMemoryStore
from app.memory.controller.cache import MemoryCache
from app.memory.controller.lifecycle_manager import LifecycleManager
from app.memory.controller.ranker import MemoryRanker
from app.memory.manager import MemoryManager
from app.memory.session_manager import SessionManager
from app.memory.sqlite_store import SQLiteStore
from app.memory.time_utils import normalize_datetime
from app.intelligence.retrieval import RetrievalEngine
from app.memory.controller.facade import MemoryController


def test_naive_and_aware_timestamps_normalize_to_utc():
    naive = normalize_datetime("2026-08-03T10:00:00")
    aware = normalize_datetime("2026-08-03T10:00:00+05:30")

    assert naive is not None and naive.tzinfo == timezone.utc
    assert aware is not None and aware.tzinfo == timezone.utc
    assert aware.hour == 4 and aware.minute == 30


def test_memory_ranker_handles_legacy_naive_created_at():
    ranker = MemoryRanker()
    item = type("Item", (), {"metadata": {"created_at": "2026-08-03T10:00:00", "confidence": 1.0, "importance": 0.5, "access_counter": 1}})()
    score = ranker.score(item)
    assert score > 0


def test_lifecycle_manager_handles_legacy_naive_timestamps(tmp_path):
    manager = MemoryManager()
    controller = MemoryController(manager)
    lifecycle = LifecycleManager(manager, MemoryCache())

    item = MemoryItem(
        id="mem-1",
        content="legacy",
        category=MemoryType.CONTEXT,
        created_at=datetime(2026, 7, 1, 12, 0, 0),
        updated_at=datetime(2026, 7, 1, 12, 0, 0),
        metadata={"memory_type": "conversation", "created_at": "2026-07-01T12:00:00", "last_accessed": "2026-07-01T12:00:00"},
    )
    manager.store_memory(item)

    assert lifecycle.expire_old_memories(now=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)) >= 0


def test_session_retrieval_with_naive_storage_timestamps(tmp_path):
    sessions = SessionManager(base_dir=tmp_path, clock=lambda: "2026-08-03T10:00:00+00:00")
    session = sessions.create_session(session_id="session-a")
    sessions.add_memory_entry(session.session_id, "topic", "hello world", "fact")

    meta_path = tmp_path / "sessions" / session.session_id / "metadata.json"
    data = meta_path.read_text(encoding="utf-8")
    meta_path.write_text(data.replace("+00:00", ""), encoding="utf-8")

    fresh = SessionManager(base_dir=tmp_path, clock=lambda: "2026-08-03T10:00:00+00:00")
    loaded = fresh.load_session(session.session_id)
    assert loaded.metadata.created_at.endswith("T10:00:00")

    controller = MemoryController(MemoryManager())
    retrieval = RetrievalEngine(controller, session_manager=sessions)
    bundle = retrieval.assemble_context("hello world", session_id=session.session_id)
    assert bundle.evidence is not None


def test_cache_expiration_and_cross_session_retrieval_remain_stable(tmp_path):
    sessions = SessionManager(base_dir=tmp_path, clock=lambda: "2026-08-03T10:00:00+00:00")
    first = sessions.create_session(session_id="session-a")
    sessions.add_memory_entry(first.session_id, "topic", "shared detail", "fact")
    second = sessions.create_session(session_id="session-b")
    sessions.add_memory_entry(second.session_id, "topic", "other detail", "fact")

    store = SQLiteStore(db_path=str(Path(tmp_path) / "memory.db"))
    manager = MemoryManager(repository=None)
    controller = MemoryController(manager)
    retrieval = RetrievalEngine(controller, session_manager=sessions)
    bundle = retrieval.assemble_context("shared detail", session_id=second.session_id)
    assert bundle.evidence

    store_entry = store.retrieve_entry("missing")
    assert store_entry is None


def test_context_memory_sorting_with_naive_created_at():
    store = ContextMemoryStore()
    item = MemoryItem(
        id="mem-1",
        content="hello",
        category=MemoryType.CONTEXT,
        created_at=datetime(2026, 8, 1, 10, 0, 0),
        updated_at=datetime(2026, 8, 1, 10, 0, 0),
        metadata={},
    )
    store.save_context(item)
    assert store.get_recent_context()[0].id == "mem-1"
