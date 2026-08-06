"""Phase 20.2.2 — Final Session Intelligence Hardening Regression Tests.

Covers:
1. Atomic session writes.
2. Schema migration layer.
3. Session rotation (archiving).
4. Corrupted file recovery.
5. Duplicate history protection.
6. Deterministic retrieval ordering.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock

from app.memory.session_manager import SessionManager
from app.memory.session_models import (
    CURRENT_SCHEMA_VERSION,
    SessionHistoryEntry,
    SessionMetadata,
)
from app.memory.session_store import (
    _METADATA_FIELD_DEFAULTS,
    migrate_session_data,
    session_memory_json_path,
)


def _sm(tmp_path: Path, **kwargs) -> SessionManager:
    return SessionManager(base_dir=tmp_path, **kwargs)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ===========================================================================
# 1. Atomic Writes
# ===========================================================================

class TestAtomicWrites:
    def test_write_json_is_atomic(self, tmp_path: Path) -> None:
        from app.memory.session_store import write_json, read_json
        target = tmp_path / "test.json"
        write_json(target, {"hello": "world"})
        assert read_json(target) == {"hello": "world"}
        
        # We can't easily simulate a mid-write crash, but we can verify it doesn't leave temp files.
        tmps = list(tmp_path.glob("*.tmp"))
        assert not tmps, "Temporary files were left behind"

    def test_write_text_atomic(self, tmp_path: Path) -> None:
        from app.memory.session_store import write_text_atomic
        target = tmp_path / "test.md"
        write_text_atomic(target, "hello world")
        assert target.read_text(encoding="utf-8") == "hello world"


# ===========================================================================
# 2. Schema Migration
# ===========================================================================

class TestSchemaMigration:
    def test_migrate_metadata_adds_missing_fields(self) -> None:
        raw_v0 = {"session_id": "test-1", "created_at": _now(), "updated_at": _now()}
        migrated = migrate_session_data(raw_v0, kind="metadata")
        
        assert migrated["schema_version"] == CURRENT_SCHEMA_VERSION
        # Check a few specific Phase 20.2 lists are initialized
        assert migrated["tools_used"] == []
        assert migrated["files_created"] == []
        assert "message_count" in migrated

    def test_migrate_memory_adds_missing_fields(self) -> None:
        raw_v0 = {"session_id": "test-2"}
        migrated = migrate_session_data(raw_v0, kind="memory")
        
        assert migrated["schema_version"] == CURRENT_SCHEMA_VERSION
        assert migrated["history"] == []
        assert migrated["next_turn_number"] == 1

    def test_migration_is_idempotent(self) -> None:
        raw_v0 = {"session_id": "test-3"}
        migrated1 = migrate_session_data(raw_v0, kind="metadata")
        migrated2 = migrate_session_data(migrated1, kind="metadata")
        assert migrated1 == migrated2

    def test_migration_preserves_existing_data(self) -> None:
        raw = {
            "session_id": "test-4",
            "schema_version": 1,
            "tools_used": ["pytest"],
            "custom_unknown_field": "preserved",
        }
        migrated = migrate_session_data(raw, kind="metadata")
        assert migrated["tools_used"] == ["pytest"]
        assert migrated["custom_unknown_field"] == "preserved"


# ===========================================================================
# 3. Session Rotation
# ===========================================================================

class TestSessionRotation:
    def test_rotation_moves_old_entries_to_archive(self, tmp_path: Path) -> None:
        sm = _sm(tmp_path, max_history_entries=2)
        sm.create_session(session_id="rot-1")
        
        # Add 3 entries (limit is 2)
        for i in range(3):
            sm.append_history("rot-1", SessionHistoryEntry(
                id=f"evt-{i}", timestamp=_now(), role="user", content=f"msg {i}"
            ))
            
        session = sm.load_session("rot-1")
        # Should only have the last 2 entries
        assert len(session.memory.history) == 2
        assert session.memory.history[0].id == "evt-1"
        assert session.memory.history[1].id == "evt-2"
        
        # Archive should have the first entry
        archived = sm.load_archived_history("rot-1")
        assert len(archived) == 1
        assert archived[0].id == "evt-0"

    def test_unlimited_history_does_not_rotate(self, tmp_path: Path) -> None:
        sm = _sm(tmp_path, max_history_entries=None)
        sm.create_session(session_id="rot-2")
        
        for i in range(3):
            sm.append_history("rot-2", SessionHistoryEntry(
                id=f"evt-{i}", timestamp=_now(), role="user", content=f"msg {i}"
            ))
            
        session = sm.load_session("rot-2")
        assert len(session.memory.history) == 3
        archived = sm.load_archived_history("rot-2")
        assert len(archived) == 0


# ===========================================================================
# 4. Corrupted File Recovery
# ===========================================================================

class TestSessionRecovery:
    def test_recover_corrupt_memory_json(self, tmp_path: Path) -> None:
        sm = _sm(tmp_path)
        sm.create_session(session_id="rec-1")
        
        # Corrupt the memory file
        mem_path = session_memory_json_path(tmp_path, "rec-1")
        mem_path.write_text("{bad json...", encoding="utf-8")
        
        session = sm.load_session("rec-1")
            
        assert session.session_id == "rec-1"
        assert len(session.memory.history) == 0

    def test_recover_corrupt_metadata_json(self, tmp_path: Path) -> None:
        from app.memory.session_store import metadata_path
        sm = _sm(tmp_path)
        sm.create_session(session_id="rec-2")
        
        meta_path = metadata_path(tmp_path, "rec-2")
        meta_path.write_text("{bad json...", encoding="utf-8")
        
        session = sm.load_session("rec-2")
            
        assert session.metadata.session_id == "rec-2"


# ===========================================================================
# 5. Duplicate Protection
# ===========================================================================

class TestDuplicateProtection:
    def test_append_history_skips_duplicates(self, tmp_path: Path) -> None:
        sm = _sm(tmp_path)
        sm.create_session(session_id="dup-1")
        
        evt = SessionHistoryEntry(id="evt-dup", timestamp=_now(), role="user", content="hello")
        
        sm.append_history("dup-1", evt)
        sm.append_history("dup-1", evt) # Should be ignored
        
        session = sm.load_session("dup-1")
        assert len(session.memory.history) == 1
        assert session.memory.history[0].id == "evt-dup"


# ===========================================================================
# 6. Deterministic Retrieval Ordering
# ===========================================================================

class TestRetrievalDeterminism:
    def test_retrieval_sort_is_fully_deterministic(self) -> None:
        from app.intelligence.retrieval import RetrievalEngine, ContextEvidence
        engine = RetrievalEngine(memory_controller=MagicMock())
        
        e1 = ContextEvidence(item_id="id1", source="session", content="", provenance="", confidence=0.9, freshness="active", scope="session", selected_reason="turn 10", timestamp="2026-08-01T10:00:00Z")
        e2 = ContextEvidence(item_id="id2", source="session", content="", provenance="", confidence=0.9, freshness="active", scope="session", selected_reason="turn 5", timestamp="2026-08-01T10:00:00Z")
        e3 = ContextEvidence(item_id="id3", source="session", content="", provenance="", confidence=0.9, freshness="active", scope="session", selected_reason="turn 5", timestamp="2026-08-01T11:00:00Z")
        
        # Expected sort order: 
        # e3 (turn 5, newer timestamp), e2 (turn 5, older timestamp), e1 (turn 10)
        # Wait, the sort key is:
        # source_tier, -confidence, freshness, timestamp, turn_number, item_id
        # Let's check timestamp. It's lexicographic ascending, so "2026-08-01T10:00:00Z" comes before "2026-08-01T11:00:00Z".
        # So e2 < e3 based on timestamp.
        # Let's verify the behavior.
        
        sorted_evs = engine._rank_and_dedupe([e3, e1, e2])
        ids = [e.item_id for e in sorted_evs]
        
        # Turn 10 vs Turn 5 doesn't matter if timestamps differ, timestamp takes precedence!
        # Actually timestamp ascending means older timestamps come first. 
        # 2026-08-01T10 (e1, e2) < 2026-08-01T11 (e3)
        # For e1 and e2, timestamp is same. turn 5 (e2) < turn 10 (e1).
        # Expected: e2, e1, e3.
        assert ids == ["id2", "id1", "id3"]
