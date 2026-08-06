"""Phase 10.1 — Session Memory Architecture acceptance tests.

Covers: session creation, loading, saving, deletion, session index updates,
deterministic session ids, metadata consistency, markdown export generation,
JSON as the single source of truth, delete-everything, the boundary rule that
personality never enumerates unrelated preferences, and retrieval that only
ever uses the relevant session.
"""

import json
import re
from types import SimpleNamespace

import pytest

from app.memory import (
    DEFAULT_BASE_DIR,
    SessionManager,
    export_session_markdown,
    metadata_path,
    session_dir,
    session_memory_json_path,
    session_memory_md_path,
)
from app.memory.session_models import SessionMemoryEntry

_ID_PATTERN = re.compile(r"^session-\d{14}-\d{4}$")


def fixed_clock(*stamps: str):
    values = list(stamps) or ["2026-08-01T12:00:00+00:00"]
    state = {"i": 0}

    def _clock() -> str:
        value = values[min(state["i"], len(values) - 1)]
        state["i"] += 1
        return value

    return _clock


# ----------------------------------------------------------------------
# Session creation
# ----------------------------------------------------------------------


def test_session_creation_persists_folder_index_and_files(tmp_path):
    manager = SessionManager(base_dir=tmp_path, clock=fixed_clock())
    session = manager.create_session(title="Debugging the API")

    assert _ID_PATTERN.match(session.session_id)
    assert session.metadata.title == "Debugging the API"
    assert session.metadata.created_at == session.metadata.updated_at
    assert session.metadata.message_count == 0
    assert manager.session_exists(session.session_id)

    folder = session_dir(tmp_path, session.session_id)
    assert (folder / "metadata.json").exists()
    assert (folder / "session_memory.json").exists()
    assert (folder / "session_memory.md").exists()
    assert (tmp_path / "session_index.json").exists()


def test_explicit_session_id_is_used_and_duplicates_rejected(tmp_path):
    manager = SessionManager(base_dir=tmp_path, clock=fixed_clock())
    session = manager.create_session(session_id="my-session-abc_1")
    assert session.session_id == "my-session-abc_1"

    with pytest.raises(ValueError):
        manager.create_session(session_id="my-session-abc_1")


def test_invalid_session_ids_rejected(tmp_path):
    manager = SessionManager(base_dir=tmp_path, clock=fixed_clock())
    with pytest.raises(ValueError):
        manager.create_session(session_id="../escape")
    with pytest.raises(ValueError):
        manager.create_session(session_id="bad id with spaces")
    with pytest.raises(ValueError):
        manager.create_session(session_id="slash/path")


# ----------------------------------------------------------------------
# Deterministic session ids
# ----------------------------------------------------------------------


def test_session_ids_are_deterministic_and_monotonic(tmp_path):
    manager = SessionManager(base_dir=tmp_path, clock=fixed_clock("2026-08-01T12:00:00+00:00"))
    first = manager.create_session()
    second = manager.create_session()

    assert _ID_PATTERN.match(first.session_id)
    assert _ID_PATTERN.match(second.session_id)
    assert first.session_id == "session-20260801120000-0001"
    assert second.session_id == "session-20260801120000-0002"
    assert first.session_id != second.session_id


# ----------------------------------------------------------------------
# Loading / saving
# ----------------------------------------------------------------------


def test_session_loading_from_disk(tmp_path):
    first = SessionManager(base_dir=tmp_path, clock=fixed_clock())
    session = first.create_session(title="Loaded later")

    second = SessionManager(base_dir=tmp_path, clock=fixed_clock())
    loaded = second.load_session(session.session_id)

    assert loaded == session
    assert loaded.metadata.title == "Loaded later"


def test_session_saving_persists_memory_and_metadata(tmp_path):
    manager = SessionManager(base_dir=tmp_path, clock=fixed_clock())
    session = manager.create_session()
    session.memory.entries.append(
        SessionMemoryEntry(key="task", value="fix api", category="task", created_at="t", updated_at="t")
    )
    session.metadata.title = "Saved"
    manager.save_session(session)

    other = SessionManager(base_dir=tmp_path, clock=fixed_clock())
    loaded = other.load_session(session.session_id)
    assert loaded.metadata.title == "Saved"
    assert loaded.memory.entries[0].key == "task"
    assert loaded.memory.entries[0].value == "fix api"


def test_load_missing_session_raises_key_error(tmp_path):
    manager = SessionManager(base_dir=tmp_path, clock=fixed_clock())
    with pytest.raises(KeyError):
        manager.load_session("session-00000000000000-0001")


# ----------------------------------------------------------------------
# Session memory entries
# ----------------------------------------------------------------------


def test_add_memory_entry_upserts_by_key_preserving_created_at(tmp_path):
    manager = SessionManager(
        base_dir=tmp_path,
        clock=fixed_clock(
            "2026-08-01T12:00:00+00:00",
            "2026-08-01T12:10:00+00:00",
            "2026-08-01T12:20:00+00:00",
        ),
    )
    session = manager.create_session()
    manager.add_memory_entry(session.session_id, "task", "first", category="task")
    entry = manager.add_memory_entry(session.session_id, "task", "second", category="task")

    assert entry.value == "second"
    assert entry.created_at == "2026-08-01T12:10:00+00:00"
    assert entry.updated_at == "2026-08-01T12:20:00+00:00"
    memory = manager.get_session_memory(session.session_id)
    assert len(memory.entries) == 1
    assert memory.entries[0].value == "second"


def test_retrieval_uses_only_relevant_session(tmp_path):
    manager = SessionManager(base_dir=tmp_path, clock=fixed_clock())
    manager.create_session(session_id="session-a")
    manager.create_session(session_id="session-b")
    manager.add_memory_entry("session-a", "project", "samaktha api", category="context")
    manager.add_memory_entry("session-b", "project", "cli tool", category="context")

    assert [e.value for e in manager.get_session_memory("session-a").entries] == ["samaktha api"]
    assert [e.value for e in manager.load_session("session-b").memory.entries] == ["cli tool"]

    session_a_json = session_memory_json_path(tmp_path, "session-a").read_text(encoding="utf-8")
    assert "samaktha api" in session_a_json
    assert "cli tool" not in session_a_json

    folder_b = session_dir(tmp_path, "session-b")
    assert "cli tool" in (folder_b / "session_memory.json").read_text(encoding="utf-8")
    assert "samaktha api" not in (folder_b / "session_memory.json").read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# Metadata consistency and session index
# ----------------------------------------------------------------------


def test_metadata_consistency_across_updates(tmp_path):
    manager = SessionManager(
        base_dir=tmp_path,
        clock=fixed_clock("2026-08-01T12:00:00+00:00", "2026-08-02T09:30:00+00:00"),
    )
    session = manager.create_session(title="T")
    assert session.metadata.created_at == "2026-08-01T12:00:00+00:00"
    assert session.metadata.updated_at == session.metadata.created_at

    manager.update_metadata(session.session_id, message_count=4)
    assert session.metadata.updated_at == "2026-08-02T09:30:00+00:00"

    entry = manager.index.get(session.session_id)
    assert entry.created_at == "2026-08-01T12:00:00+00:00"
    assert entry.updated_at == "2026-08-02T09:30:00+00:00"


def test_session_index_stores_metadata_only(tmp_path):
    manager = SessionManager(base_dir=tmp_path, clock=fixed_clock())
    manager.create_session(session_id="session-a")
    manager.add_memory_entry("session-a", "task", "secret value", category="task")

    raw = json.loads((tmp_path / "session_index.json").read_text(encoding="utf-8"))
    assert set(raw.keys()) == {"session-a"}
    entry_keys = set(raw["session-a"].keys())
    assert entry_keys == {
        "session_id",
        "created_at",
        "updated_at",
        "title",
        "summary",
        "tags",
        "projects",
        "message_count",
        "topic_summary",
        # Phase 20.2 deterministic extraction fields
        "tools_used",
        "providers_used",
        "files_created",
        "files_modified",
        "files_deleted",
        "approvals",
        "architecture_topics",
        "bugs_fixed",
        "repositories",
        "runtime_errors",
        "milestones",
        # Phase 20.2.1 hardening
        "schema_version",
    }
    assert "secret value" not in json.dumps(raw)

    for metadata in manager.list_sessions():
        dumped = metadata.model_dump()
        assert "entries" not in dumped
        assert "value" not in dumped


def test_update_metadata_reflects_in_index_and_disk(tmp_path):
    manager = SessionManager(base_dir=tmp_path, clock=fixed_clock())
    session = manager.create_session()
    manager.update_metadata(
        session.session_id,
        title="New Title",
        tags=["a", "b"],
        projects=["samaktha"],
        message_count=3,
    )

    entry = manager.index.get(session.session_id)
    assert entry.title == "New Title"
    assert entry.tags == ["a", "b"]
    assert entry.projects == ["samaktha"]
    assert entry.message_count == 3

    raw = json.loads(metadata_path(tmp_path, session.session_id).read_text(encoding="utf-8"))
    assert raw["title"] == "New Title"


def test_list_sessions_orders_deterministically(tmp_path):
    manager = SessionManager(
        base_dir=tmp_path,
        clock=fixed_clock(
            "2026-08-01T12:00:00+00:00",
            "2026-08-01T13:00:00+00:00",
            "2026-08-01T14:00:00+00:00",
        ),
    )
    first = manager.create_session()
    manager.add_memory_entry(first.session_id, "k", "v")
    second = manager.create_session()

    order = [entry.session_id for entry in manager.list_sessions()]
    assert order == [second.session_id, first.session_id]


# ----------------------------------------------------------------------
# Markdown export
# ----------------------------------------------------------------------


def test_markdown_export_generation_matches_expected(tmp_path):
    manager = SessionManager(base_dir=tmp_path, clock=fixed_clock())
    session = manager.create_session(title="Hello")
    manager.add_memory_entry(session.session_id, "task", "debug api", category="task")

    expected = export_session_markdown(session.metadata, session.memory)
    markdown = session_memory_md_path(tmp_path, session.session_id).read_text(encoding="utf-8")
    assert markdown == expected
    assert "# Session" in markdown
    assert "debug api" in markdown


# ----------------------------------------------------------------------
# JSON is the source of truth
# ----------------------------------------------------------------------


def test_json_remains_source_of_truth(tmp_path):
    manager = SessionManager(base_dir=tmp_path, clock=fixed_clock())
    session = manager.create_session()
    manager.add_memory_entry(session.session_id, "task", "v1")

    markdown_path = session_memory_md_path(tmp_path, session.session_id)
    markdown_path.write_text("GARBAGE", encoding="utf-8")

    loaded = manager.load_session(session.session_id)
    assert loaded.memory.entries[0].value == "v1"

    manager.save_session(loaded)
    assert "GARBAGE" not in markdown_path.read_text(encoding="utf-8")
    assert "v1" in markdown_path.read_text(encoding="utf-8")

    json_path = session_memory_json_path(tmp_path, session.session_id)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["entries"][0]["value"] = "v2"
    json_path.write_text(json.dumps(data), encoding="utf-8")

    fresh = SessionManager(base_dir=tmp_path, clock=fixed_clock())
    reloaded = fresh.load_session(session.session_id)
    assert reloaded.memory.entries[0].value == "v2"


# ----------------------------------------------------------------------
# Forgetting
# ----------------------------------------------------------------------


def test_delete_session_removes_folder_index_and_cache(tmp_path):
    manager = SessionManager(base_dir=tmp_path, clock=fixed_clock())
    first = manager.create_session()
    second = manager.create_session()

    assert manager.delete_session(first.session_id) is True
    assert manager.session_exists(first.session_id) is False
    assert manager.session_exists(second.session_id) is True
    assert not session_dir(tmp_path, first.session_id).exists()

    with pytest.raises(KeyError):
        manager.load_session(first.session_id)

    assert manager.delete_session(first.session_id) is False
    assert manager.delete_session("session-00000000000000-0001") is False


def test_delete_everything_clears_all_sessions_and_index(tmp_path):
    manager = SessionManager(base_dir=tmp_path, clock=fixed_clock())
    first = manager.create_session()
    second = manager.create_session()
    manager.add_memory_entry(second.session_id, "task", "value")

    manager.delete_everything()

    assert manager.list_sessions() == []
    assert not (tmp_path / "sessions").exists()
    assert len(manager.index) == 0
    raw = json.loads((tmp_path / "session_index.json").read_text(encoding="utf-8"))
    assert raw == {}
    with pytest.raises(KeyError):
        manager.load_session("session-00000000000000-0001")


class FakeController:
    def __init__(self):
        self.deleted_types = []
        self.cache_cleared = False

    def delete_by_type(self, memory_type):
        self.deleted_types.append(memory_type)

    def clear_cache(self):
        self.cache_cleared = True


def test_delete_everything_requests_long_term_memory_deletion(tmp_path):
    controller = FakeController()
    manager = SessionManager(base_dir=tmp_path, memory_controller=controller, clock=fixed_clock())
    manager.create_session()

    manager.delete_everything()

    assert set(controller.deleted_types) == {
        "conversation",
        "document",
        "preference",
        "workflow",
        "tool",
        "knowledge",
        "system",
    }
    assert controller.cache_cleared is True


def test_delete_everything_without_controller_is_safe(tmp_path):
    manager = SessionManager(base_dir=tmp_path, clock=fixed_clock())
    manager.create_session()
    manager.delete_everything()
    assert manager.list_sessions() == []


# ----------------------------------------------------------------------
# Personality boundary: never enumerate unrelated preferences
# ----------------------------------------------------------------------


def _make_preference_item(memory_id, content):
    return SimpleNamespace(
        id=memory_id,
        content=content,
        metadata={
            "memory_type": "preference",
            "tags": ["preference"],
            "entities": [],
            "source": "",
            "importance": 0.6,
            "created_at": "2025-01-01T00:00:00",
            "last_accessed": "2025-01-01T00:00:00",
        },
    )


def test_personality_never_lists_unrelated_preferences_on_greeting():
    from app.personality import PersonalityEngine

    preferences = [
        _make_preference_item("pref-1", "user prefers french press coffee"),
        _make_preference_item("pref-2", "user prefers dark theme"),
        _make_preference_item("pref-3", "user prefers python over typescript"),
    ]
    evaluation = PersonalityEngine().evaluate("Hello there!", retrieved_memories=preferences)

    assert evaluation.greeting.is_greeting is True
    assert evaluation.visible_memories == []
    assert evaluation.suppressed_count == len(preferences)


# ----------------------------------------------------------------------
# Default base dir
# ----------------------------------------------------------------------


def test_default_base_dir_is_data_session_memory():
    assert DEFAULT_BASE_DIR == "data/session_memory"
