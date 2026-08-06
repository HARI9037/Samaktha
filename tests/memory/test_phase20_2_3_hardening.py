import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from app.memory.session_manager import SessionManager
from app.memory.session_models import SessionHistoryEntry, SessionMetadata, SessionMemory
from app.memory.session_store import migrate_session_data, metadata_path, session_memory_json_path, session_dir
from app.intelligence.retrieval import RetrievalEngine

_ARCHIVE_FILENAME = "session_memory_archive.json"

def test_schema_migration_hardening():
    # 1. Null schema_version
    data_null = {"schema_version": None, "session_id": "test-1"}
    migrated = migrate_session_data(data_null, kind="metadata")
    assert migrated["schema_version"] == 1
    assert "tools_used" in migrated

    # 2. Future schema_version should be untouched
    data_future = {"schema_version": 99, "session_id": "test-2", "future_field": True}
    migrated = migrate_session_data(data_future, kind="metadata")
    assert migrated["schema_version"] == 99
    assert "tools_used" not in migrated  # Should not apply defaults
    assert migrated["future_field"] is True

    # 3. Backward migration (v0 -> v1) still works
    data_old = {"session_id": "test-3"} # no schema_version
    migrated = migrate_session_data(data_old, kind="metadata")
    assert migrated["schema_version"] == 1
    assert "tools_used" in migrated


def test_session_recovery_hardening():
    base_dir = Path(tempfile.mkdtemp())
    try:
        sm = SessionManager(base_dir=base_dir, max_history_entries=2)
        sess = sm.create_session(session_id="recovery-test")
        
        # Corrupt metadata file
        meta_file = metadata_path(base_dir, "recovery-test")
        with open(meta_file, "r") as f:
            meta_json = json.load(f)
        meta_json["message_count"] = "invalid_string"  # causes ValidationError
        meta_json["title"] = "Valid Title"
        with open(meta_file, "w") as f:
            json.dump(meta_json, f)

        # Corrupt memory file
        mem_file = session_memory_json_path(base_dir, "recovery-test")
        with open(mem_file, "r") as f:
            mem_json = json.load(f)
        mem_json["next_turn_number"] = "invalid"  # causes ValidationError
        mem_json["entries"] = [{"key": "test_fact", "value": "123", "category": "fact", "created_at": "now", "updated_at": "now"}]
        with open(mem_file, "w") as f:
            json.dump(mem_json, f)

        # Clear cache to force reload
        sm._cache.clear()

        # Load session and check if valid fields survived
        sess_loaded = sm.load_session("recovery-test")
        assert sess_loaded.metadata.title == "Valid Title", "Valid metadata field should survive"
        assert sess_loaded.metadata.message_count == 0, "Invalid metadata field should fallback"
        assert len(sess_loaded.memory.entries) == 1, "Valid memory entries should survive"
        assert sess_loaded.memory.entries[0].key == "test_fact"

        # Corrupt archive file
        archive_file = session_dir(base_dir, "recovery-test") / _ARCHIVE_FILENAME
        with open(archive_file, "w") as f:
            f.write("{invalid_json]") # completely malformed
        
        # Trigger rotation
        sm.append_history("recovery-test", SessionHistoryEntry(id="1", timestamp="now", role="user", content="msg 1"))
        sm.append_history("recovery-test", SessionHistoryEntry(id="2", timestamp="now", role="assistant", content="msg 2"))
        sm.append_history("recovery-test", SessionHistoryEntry(id="3", timestamp="now", role="user", content="msg 3")) # forces rotation

        # Verify new archive is created and old corrupt one is backed up
        assert archive_file.exists()
        bak_file = archive_file.with_suffix(".json.bak")
        assert bak_file.exists(), "Corrupted archive must be backed up"
        
        with open(archive_file, "r") as f:
            archive_json = json.load(f)
            assert isinstance(archive_json, list)
            assert len(archive_json) == 1
            assert archive_json[0]["id"] == "1"
    finally:
        shutil.rmtree(base_dir)


def test_archive_retrieval_hardening():
    base_dir = Path(tempfile.mkdtemp())
    try:
        sm = SessionManager(base_dir=base_dir, max_history_entries=1)
        sess = sm.create_session(session_id="retrieval-test")
        
        # Add 3 history entries. The first 2 will be rotated to archive.
        sm.append_history("retrieval-test", SessionHistoryEntry(id="h1", timestamp="T1", role="user", content="first archived msg"))
        sm.append_history("retrieval-test", SessionHistoryEntry(id="h2", timestamp="T2", role="user", content="second archived msg"))
        sm.append_history("retrieval-test", SessionHistoryEntry(id="h3", timestamp="T3", role="user", content="third active msg"))
        
        re = RetrievalEngine(memory_controller=None, session_manager=sm)
        
        # Test current session
        current_evidence = re._from_current_session("retrieval-test", "msg")
        assert len(current_evidence) == 3
        # Check ordering and provenance
        assert current_evidence[0].item_id == "retrieval-test:hist:h1"
        assert current_evidence[0].freshness == "archived"
        assert current_evidence[1].item_id == "retrieval-test:hist:h2"
        assert current_evidence[1].freshness == "archived"
        assert current_evidence[2].item_id == "retrieval-test:hist:h3"
        assert current_evidence[2].freshness == "active"

        # Test cross session
        cross_evidence = re._from_session_history("search_term", "other_session", top_k=10, cross_session=True)
        # Check if the archived messages were found
        hist_items = [e for e in cross_evidence if e.source == "session_history"]
        assert len(hist_items) == 3
        assert hist_items[0].item_id == "retrieval-test:hist:h1"
        assert hist_items[0].freshness == "archived"
        assert hist_items[2].item_id == "retrieval-test:hist:h3"
        assert hist_items[2].freshness == "active"

    finally:
        shutil.rmtree(base_dir)
