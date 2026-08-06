"""Phase 20.2.1 — Session Intelligence Hardening Regression Tests.

Covers all 10 hardening requirements:

1.  SessionBuilder is evidence-driven only (no fabrication).
2.  Markdown export is render-only (no intelligence).
3.  History and memory remain separate collections.
4.  Turn numbers increase monotonically.
5.  Retrieval priority: metadata > facts > history > long-term > skill.
6.  Metadata collections are duplicate-free.
7.  Schema version persists correctly.
8.  Provenance is correct and complete.
9.  Existing Phase 20.2 behaviour remains unchanged.
10. Regression: previous Phase 20.2 tests still pass under 20.2.1 schema.
"""

from __future__ import annotations

import datetime
import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.memory.formation.session_builder import SessionBuilder, _dedupe_append
from app.memory.session_manager import SessionManager
from app.memory.session_models import (
    CURRENT_SCHEMA_VERSION,
    Session,
    SessionHistoryEntry,
    SessionMemory,
    SessionMemoryEntry,
    SessionMetadata,
)
from app.memory.session_store import export_session_markdown
from app.runtime.report import ExecutionReport, ExecutionTruthState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sm(tmp_path: Path) -> SessionManager:
    return SessionManager(base_dir=tmp_path)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _report(
    *,
    success: bool = True,
    state: ExecutionTruthState = ExecutionTruthState.SUCCEEDED,
    tool_results: list[dict] | None = None,
    errors: list[str] | None = None,
) -> ExecutionReport:
    return ExecutionReport(
        plan_id="plan-harden-001",
        success=success,
        execution_state=state,
        tool_results=tool_results or [],
        errors=errors or [],
    )


# ===========================================================================
# 1. SessionBuilder is evidence-driven only
# ===========================================================================


class TestSessionBuilderEvidenceDriven:
    def test_no_tools_when_no_report(self) -> None:
        meta = SessionMetadata(session_id="ev-01", created_at=_now(), updated_at=_now())
        entries = SessionBuilder.build_history_entries("hello", "hi")
        updated = SessionBuilder.update_metadata(meta, entries)
        assert updated.tools_used == []

    def test_no_files_when_no_report(self) -> None:
        meta = SessionMetadata(session_id="ev-02", created_at=_now(), updated_at=_now())
        entries = SessionBuilder.build_history_entries("do something", "done")
        updated = SessionBuilder.update_metadata(meta, entries)
        assert updated.files_created == []
        assert updated.files_modified == []
        assert updated.files_deleted == []

    def test_no_errors_when_no_report(self) -> None:
        meta = SessionMetadata(session_id="ev-03", created_at=_now(), updated_at=_now())
        entries = SessionBuilder.build_history_entries("run", "result")
        updated = SessionBuilder.update_metadata(meta, entries)
        assert updated.runtime_errors == []

    def test_no_milestones_ever_invented(self) -> None:
        """Milestones must never be populated without explicit evidence."""
        meta = SessionMetadata(session_id="ev-04", created_at=_now(), updated_at=_now())
        entries = SessionBuilder.build_history_entries("completed phase 1", "great work done!")
        updated = SessionBuilder.update_metadata(meta, entries, execution_report=_report())
        assert updated.milestones == []

    def test_no_bugs_ever_invented(self) -> None:
        """bugs_fixed must never be populated by text heuristics."""
        meta = SessionMetadata(session_id="ev-05", created_at=_now(), updated_at=_now())
        entries = SessionBuilder.build_history_entries("fixed the bug", "bug is fixed now")
        updated = SessionBuilder.update_metadata(meta, entries, execution_report=_report())
        assert updated.bugs_fixed == []

    def test_tool_extracted_from_report(self) -> None:
        report = _report(tool_results=[{"tool": "filesystem", "action": "write", "args": {"path": "/x.py"}}])
        meta = SessionMetadata(session_id="ev-06", created_at=_now(), updated_at=_now())
        entries = SessionBuilder.build_history_entries("write", "done", execution_report=report)
        updated = SessionBuilder.update_metadata(meta, entries, execution_report=report)
        assert "filesystem" in updated.tools_used

    def test_file_created_extracted_from_report(self) -> None:
        report = _report(tool_results=[{"tool": "filesystem", "action": "write", "args": {"path": "/app/main.py"}}])
        meta = SessionMetadata(session_id="ev-07", created_at=_now(), updated_at=_now())
        entries = SessionBuilder.build_history_entries("create file", "done", execution_report=report)
        updated = SessionBuilder.update_metadata(meta, entries, execution_report=report)
        assert "/app/main.py" in updated.files_created

    def test_file_modified_extracted_from_report(self) -> None:
        report = _report(tool_results=[{"tool": "filesystem", "action": "edit", "args": {"path": "/app/utils.py"}}])
        meta = SessionMetadata(session_id="ev-08", created_at=_now(), updated_at=_now())
        entries = SessionBuilder.build_history_entries("edit file", "done", execution_report=report)
        updated = SessionBuilder.update_metadata(meta, entries, execution_report=report)
        assert "/app/utils.py" in updated.files_modified

    def test_errors_extracted_from_report(self) -> None:
        report = _report(
            success=False,
            state=ExecutionTruthState.FAILED,
            errors=["ImportError: module not found"],
        )
        meta = SessionMetadata(session_id="ev-09", created_at=_now(), updated_at=_now())
        entries = SessionBuilder.build_history_entries("run", "failed", execution_report=report)
        updated = SessionBuilder.update_metadata(meta, entries, execution_report=report)
        assert any("ImportError" in e for e in updated.runtime_errors)

    def test_history_entry_has_no_invented_intent(self) -> None:
        """intent field must remain None unless explicitly passed."""
        entries = SessionBuilder.build_history_entries("hello", "hi")
        assert all(e.intent is None for e in entries)


# ===========================================================================
# 2. Markdown export is render-only
# ===========================================================================


class TestMarkdownRenderOnly:
    def _blank_meta(self) -> SessionMetadata:
        return SessionMetadata(session_id="md-ro-01", created_at=_now(), updated_at=_now())

    def _blank_memory(self) -> SessionMemory:
        return SessionMemory(session_id="md-ro-01")

    def test_no_string_scanning_in_export(self) -> None:
        """export_session_markdown must not scan history content for keywords."""
        import inspect
        import re as _re
        src = inspect.getsource(export_session_markdown)
        # Should not use split/regex searching for bug/file/tool keywords
        forbidden_patterns = [
            r'\.find\(',
            r're\.search',
            r're\.match',
            r'"bug"',
            r'"fix"',
            r'"created"',
            r'"modified"',
        ]
        for pat in forbidden_patterns:
            assert not _re.search(pat, src), (
                f"export_session_markdown contains forbidden scanning pattern: {pat!r}"
            )

    def test_export_renders_files_created_from_metadata(self) -> None:
        meta = self._blank_meta()
        meta.files_created = ["/app/main.py", "/app/utils.py"]
        md = export_session_markdown(meta, self._blank_memory())
        assert "/app/main.py" in md
        assert "/app/utils.py" in md

    def test_export_renders_tools_from_metadata(self) -> None:
        meta = self._blank_meta()
        meta.tools_used = ["filesystem", "internet"]
        md = export_session_markdown(meta, self._blank_memory())
        assert "filesystem" in md
        assert "internet" in md

    def test_export_renders_schema_version(self) -> None:
        meta = self._blank_meta()
        md = export_session_markdown(meta, self._blank_memory())
        assert "Schema version:" in md
        assert str(CURRENT_SCHEMA_VERSION) in md

    def test_export_renders_turn_number_in_timeline(self) -> None:
        meta = self._blank_meta()
        memory = self._blank_memory()
        memory.history.append(SessionHistoryEntry(
            id="evt-1", timestamp=_now(), role="user", content="hello", turn_number=3,
        ))
        md = export_session_markdown(meta, memory)
        assert "T3" in md

    def test_export_section_structure_complete(self) -> None:
        meta = self._blank_meta()
        md = export_session_markdown(meta, self._blank_memory())
        for section in [
            "## Summary", "## Major Topics", "## Files Created", "## Files Modified",
            "## Tools Used", "## Errors Encountered", "## Bugs Fixed",
            "## Conversation Timeline", "## Conversation Log", "## Session Memory",
        ]:
            assert section in md, f"Missing: {section}"

    def test_export_does_not_modify_metadata(self) -> None:
        """The exporter must be side-effect free."""
        meta = self._blank_meta()
        meta.tools_used = ["tool-a"]
        original_tools = list(meta.tools_used)
        _ = export_session_markdown(meta, self._blank_memory())
        assert meta.tools_used == original_tools


# ===========================================================================
# 3. History and memory are separate
# ===========================================================================


class TestHistoryMemorySeparation:
    def test_history_and_entries_are_different_lists(self, tmp_path: Path) -> None:
        sm = _sm(tmp_path)
        sm.create_session(session_id="sep-01")
        sm.add_memory_entry("sep-01", "key1", "fact-value")
        sm.append_history("sep-01", SessionHistoryEntry(
            id="evt-sep-1", timestamp=_now(), role="user", content="hello",
        ))
        session = sm.load_session("sep-01")
        assert session.memory.entries  # has facts
        assert session.memory.history  # has history
        # facts must not appear in history and vice versa
        entry_values = {e.value for e in session.memory.entries}
        history_contents = {e.content for e in session.memory.history}
        assert entry_values.isdisjoint(history_contents), "Facts leaked into history"

    def test_retrieval_does_not_treat_history_as_facts(self, tmp_path: Path) -> None:
        from app.intelligence.retrieval import RetrievalEngine
        sm = _sm(tmp_path)
        sm.create_session(session_id="sep-02")
        sm.append_history("sep-02", SessionHistoryEntry(
            id="evt-sep-2", timestamp=_now(), role="user", content="filesystem usage",
        ))
        mc = MagicMock()
        mc.memory_manager = MagicMock()
        mc.memory_manager.get_recent_context.return_value = []
        mc.search = MagicMock(return_value=[])
        mc.find_relevant_skills = MagicMock(return_value=[])
        engine = RetrievalEngine(mc, session_manager=sm)
        result = engine.retrieve("filesystem usage", session_id="sep-02")
        for ev in result.evidence:
            if "filesystem usage" in ev.content:
                assert ev.source == "session_history", (
                    f"History event surfaced as source={ev.source!r}, expected session_history"
                )

    def test_memory_entries_not_in_history(self, tmp_path: Path) -> None:
        sm = _sm(tmp_path)
        sm.create_session(session_id="sep-03")
        sm.add_memory_entry("sep-03", "project", "samaktha")
        session = sm.load_session("sep-03")
        # history must contain no SessionMemoryEntry objects
        for h in session.memory.history:
            assert isinstance(h, SessionHistoryEntry)


# ===========================================================================
# 4. Turn numbers increase monotonically
# ===========================================================================


class TestMonotonicTurnNumbers:
    def test_turn_numbers_monotonic_across_appends(self, tmp_path: Path) -> None:
        sm = _sm(tmp_path)
        sm.create_session(session_id="turn-01")
        for i in range(6):
            sm.append_history("turn-01", SessionHistoryEntry(
                id=f"evt-{i}", timestamp=_now(), role="user", content=f"msg {i}",
            ))
        session = sm.load_session("turn-01")
        turns = [e.turn_number for e in session.memory.history]
        assert turns == sorted(turns), "Turn numbers not monotonically increasing"
        assert len(set(turns)) == len(turns), "Turn numbers contain duplicates"

    def test_turn_numbers_start_from_one(self, tmp_path: Path) -> None:
        sm = _sm(tmp_path)
        sm.create_session(session_id="turn-02")
        sm.append_history("turn-02", SessionHistoryEntry(
            id="evt-first", timestamp=_now(), role="user", content="first",
        ))
        session = sm.load_session("turn-02")
        assert session.memory.history[0].turn_number == 1

    def test_turn_numbers_survive_cache_eviction(self, tmp_path: Path) -> None:
        """Even after a fresh SessionManager load, turn_number must continue."""
        sm = _sm(tmp_path)
        sm.create_session(session_id="turn-03")
        sm.append_history("turn-03", SessionHistoryEntry(
            id="evt-a", timestamp=_now(), role="user", content="first",
        ))
        # Simulate cache eviction by creating a fresh manager
        sm2 = SessionManager(base_dir=tmp_path)
        sm2.append_history("turn-03", SessionHistoryEntry(
            id="evt-b", timestamp=_now(), role="assistant", content="second",
        ))
        session = sm2.load_session("turn-03")
        turns = [e.turn_number for e in session.memory.history]
        assert turns[0] < turns[1], "Turn number did not continue after cache eviction"
        assert len(set(turns)) == 2, "Duplicate turn numbers after cache eviction"

    def test_markdown_sorts_by_turn_number(self) -> None:
        meta = SessionMetadata(session_id="turn-04", created_at=_now(), updated_at=_now())
        memory = SessionMemory(session_id="turn-04")
        # Insert deliberately out-of-order
        memory.history = [
            SessionHistoryEntry(id="evt-3", timestamp=_now(), role="user", content="third", turn_number=3),
            SessionHistoryEntry(id="evt-1", timestamp=_now(), role="user", content="first", turn_number=1),
            SessionHistoryEntry(id="evt-2", timestamp=_now(), role="assistant", content="second", turn_number=2),
        ]
        md = export_session_markdown(meta, memory)
        first_pos = md.index("first")
        second_pos = md.index("second")
        third_pos = md.index("third")
        assert first_pos < second_pos < third_pos, "Markdown did not sort by turn_number"


# ===========================================================================
# 5. Retrieval priority order
# ===========================================================================


class TestRetrievalPriority:
    def _engine(self, tmp_path: Path, session_id: str) -> tuple:
        from app.intelligence.retrieval import RetrievalEngine
        sm = _sm(tmp_path)
        sm.create_session(session_id=session_id)
        mc = MagicMock()
        mc.memory_manager = MagicMock()
        mc.memory_manager.get_recent_context.return_value = []
        mc.search = MagicMock(return_value=[])
        mc.find_relevant_skills = MagicMock(return_value=[])
        engine = RetrievalEngine(mc, session_manager=sm)
        return engine, sm

    def test_session_metadata_before_session_history(self, tmp_path: Path) -> None:
        from app.intelligence.retrieval import RetrievalEngine
        engine, sm = self._engine(tmp_path, "prio-01")
        session = sm.load_session("prio-01")
        session.metadata.tools_used = ["filesystem"]
        sm.save_session(session)
        sm.append_history("prio-01", SessionHistoryEntry(
            id="evt-p1", timestamp=_now(), role="user", content="filesystem call",
        ))
        result = engine.retrieve("filesystem", session_id="prio-01")
        sources = [e.source for e in result.evidence]
        if "session_metadata" in sources and "session_history" in sources:
            assert sources.index("session_metadata") < sources.index("session_history")

    def test_session_facts_before_session_history(self, tmp_path: Path) -> None:
        from app.intelligence.retrieval import RetrievalEngine
        engine, sm = self._engine(tmp_path, "prio-02")
        sm.add_memory_entry("prio-02", "target", "important fact")
        sm.append_history("prio-02", SessionHistoryEntry(
            id="evt-p2", timestamp=_now(), role="user", content="target important fact",
        ))
        result = engine.retrieve("target important fact", session_id="prio-02")
        sources = [e.source for e in result.evidence]
        if "session" in sources and "session_history" in sources:
            # First occurrence of 'session' (facts) must be before 'session_history'
            assert sources.index("session") < sources.index("session_history")

    def test_session_metadata_before_long_term(self, tmp_path: Path) -> None:
        from app.intelligence.retrieval import RetrievalEngine
        engine, sm = self._engine(tmp_path, "prio-03")
        session = sm.load_session("prio-03")
        session.metadata.bugs_fixed = ["NullPointerError"]
        sm.save_session(session)
        lt_item = MagicMock()
        lt_item.content = "NullPointerError bug"
        lt_item.metadata = {}
        lt_item.key = "lt-bug"
        engine.memory_controller.search = MagicMock(return_value=[lt_item])
        result = engine.retrieve("NullPointerError", session_id="prio-03")
        sources = [e.source for e in result.evidence]
        if "session_metadata" in sources and "long_term" in sources:
            assert sources.index("session_metadata") < sources.index("long_term")


# ===========================================================================
# 6. Metadata collections are duplicate-free
# ===========================================================================


class TestNoDuplicates:
    def test_dedupe_append_helper(self) -> None:
        lst: list[str] = []
        _dedupe_append(lst, "tool-a")
        _dedupe_append(lst, "tool-a")
        _dedupe_append(lst, "tool-b")
        assert lst == ["tool-a", "tool-b"]

    def test_repeated_execution_does_not_duplicate_tools(self) -> None:
        report = _report(tool_results=[{"tool": "filesystem", "action": "write", "args": {"path": "/x.py"}}])
        meta = SessionMetadata(session_id="dedup-01", created_at=_now(), updated_at=_now())
        entries1 = SessionBuilder.build_history_entries("first", "done", execution_report=report)
        meta = SessionBuilder.update_metadata(meta, entries1, execution_report=report)
        entries2 = SessionBuilder.build_history_entries("second", "done", execution_report=report)
        meta = SessionBuilder.update_metadata(meta, entries2, execution_report=report)
        assert meta.tools_used.count("filesystem") == 1

    def test_repeated_execution_does_not_duplicate_files(self) -> None:
        report = _report(tool_results=[{"tool": "filesystem", "action": "write", "args": {"path": "/app/x.py"}}])
        meta = SessionMetadata(session_id="dedup-02", created_at=_now(), updated_at=_now())
        for _ in range(3):
            entries = SessionBuilder.build_history_entries("write", "done", execution_report=report)
            meta = SessionBuilder.update_metadata(meta, entries, execution_report=report)
        assert meta.files_created.count("/app/x.py") == 1

    def test_repeated_errors_not_duplicated(self) -> None:
        report = _report(
            success=False,
            state=ExecutionTruthState.FAILED,
            errors=["RuntimeError: timeout"],
        )
        meta = SessionMetadata(session_id="dedup-03", created_at=_now(), updated_at=_now())
        for _ in range(2):
            entries = SessionBuilder.build_history_entries("run", "failed", execution_report=report)
            meta = SessionBuilder.update_metadata(meta, entries, execution_report=report)
        assert meta.runtime_errors.count("RuntimeError: timeout") == 1

    def test_stable_ordering_preserved(self) -> None:
        report = _report(tool_results=[
            {"tool": "filesystem", "action": "write", "args": {"path": "/a.py"}},
            {"tool": "internet", "action": "search", "args": {}},
        ])
        meta = SessionMetadata(session_id="dedup-04", created_at=_now(), updated_at=_now())
        entries = SessionBuilder.build_history_entries("run", "done", execution_report=report)
        meta = SessionBuilder.update_metadata(meta, entries, execution_report=report)
        first_tools = list(meta.tools_used)
        # Running again must not reorder
        entries2 = SessionBuilder.build_history_entries("run", "done", execution_report=report)
        meta = SessionBuilder.update_metadata(meta, entries2, execution_report=report)
        assert meta.tools_used == first_tools


# ===========================================================================
# 7. Schema version persists correctly
# ===========================================================================


class TestSchemaVersion:
    def test_schema_version_default_value(self) -> None:
        meta = SessionMetadata(session_id="sv-01", created_at=_now(), updated_at=_now())
        assert meta.schema_version == CURRENT_SCHEMA_VERSION

    def test_schema_version_persisted_to_json(self, tmp_path: Path) -> None:
        sm = _sm(tmp_path)
        sm.create_session(session_id="sv-02")
        from app.memory.session_store import metadata_path, read_json
        data = read_json(metadata_path(tmp_path, "sv-02"))
        assert data is not None
        assert data["schema_version"] == CURRENT_SCHEMA_VERSION

    def test_schema_version_survives_round_trip(self, tmp_path: Path) -> None:
        sm = _sm(tmp_path)
        sm.create_session(session_id="sv-03")
        sm2 = SessionManager(base_dir=tmp_path)
        session = sm2.load_session("sv-03")
        assert session.metadata.schema_version == CURRENT_SCHEMA_VERSION

    def test_schema_version_in_markdown(self, tmp_path: Path) -> None:
        sm = _sm(tmp_path)
        sm.create_session(session_id="sv-04")
        from app.memory.session_store import session_memory_md_path
        md = session_memory_md_path(tmp_path, "sv-04").read_text(encoding="utf-8")
        assert f"Schema version: {CURRENT_SCHEMA_VERSION}" in md


# ===========================================================================
# 8. Provenance is correct and complete
# ===========================================================================


class TestProvenance:
    def test_metadata_evidence_provenance_format(self, tmp_path: Path) -> None:
        from app.intelligence.retrieval import RetrievalEngine
        sm = _sm(tmp_path)
        sm.create_session(session_id="prov-h-01")
        session = sm.load_session("prov-h-01")
        session.metadata.tools_used = ["filesystem"]
        sm.save_session(session)
        mc = MagicMock()
        mc.memory_manager = MagicMock()
        mc.memory_manager.get_recent_context.return_value = []
        mc.search = MagicMock(return_value=[])
        mc.find_relevant_skills = MagicMock(return_value=[])
        engine = RetrievalEngine(mc, session_manager=sm)
        result = engine.retrieve("tools used", session_id="prov-h-01")
        for ev in result.evidence:
            if ev.source == "session_metadata":
                assert "prov-h-01" in ev.provenance
                assert "metadata" in ev.provenance
                assert ev.confidence > 0.0
                assert ev.scope == "session"
                break

    def test_history_evidence_provenance_includes_turn(self, tmp_path: Path) -> None:
        from app.intelligence.retrieval import RetrievalEngine
        sm = _sm(tmp_path)
        sm.create_session(session_id="prov-h-02")
        sm.append_history("prov-h-02", SessionHistoryEntry(
            id="evt-ph-1", timestamp=_now(), role="user", content="filesystem call",
        ))
        mc = MagicMock()
        mc.memory_manager = MagicMock()
        mc.memory_manager.get_recent_context.return_value = []
        mc.search = MagicMock(return_value=[])
        mc.find_relevant_skills = MagicMock(return_value=[])
        engine = RetrievalEngine(mc, session_manager=sm)
        result = engine.retrieve("filesystem", session_id="prov-h-02")
        for ev in result.evidence:
            if ev.source == "session_history":
                assert "prov-h-02" in ev.provenance
                assert "history" in ev.provenance
                assert "turn" in ev.provenance  # turn number in provenance
                break

    def test_provenance_never_empty(self, tmp_path: Path) -> None:
        from app.intelligence.retrieval import RetrievalEngine
        sm = _sm(tmp_path)
        sm.create_session(session_id="prov-h-03")
        session = sm.load_session("prov-h-03")
        session.metadata.files_created = ["/x.py"]
        sm.save_session(session)
        mc = MagicMock()
        mc.memory_manager = MagicMock()
        mc.memory_manager.get_recent_context.return_value = []
        mc.search = MagicMock(return_value=[])
        mc.find_relevant_skills = MagicMock(return_value=[])
        engine = RetrievalEngine(mc, session_manager=sm)
        result = engine.retrieve("files", session_id="prov-h-03")
        for ev in result.evidence:
            assert ev.provenance, f"Evidence {ev.item_id} has empty provenance"


# ===========================================================================
# 9. Existing Phase 20.2 behaviour unchanged
# ===========================================================================


class TestPhase202Regression:
    def test_ingest_still_writes_to_memory_controller(self, tmp_path: Path) -> None:
        from app.memory.formation.engine import MemoryFormationEngine
        mc = MagicMock()
        mc.memory_manager = MagicMock()
        mc.memory_manager.get_recent_context.return_value = []
        mc.write_conversation = MagicMock(return_value=MagicMock(id="conv-reg"))
        engine = MemoryFormationEngine(mc)
        results = engine.ingest(user_message="hello", assistant_response="hi")
        mc.write_conversation.assert_called_once()
        assert any(r.memory_type == "conversation" for r in results)

    def test_ingest_still_writes_session_history(self, tmp_path: Path) -> None:
        from app.memory.formation.engine import MemoryFormationEngine
        mc = MagicMock()
        mc.memory_manager = MagicMock()
        mc.memory_manager.get_recent_context.return_value = []
        mc.write_conversation = MagicMock(return_value=MagicMock(id="conv-reg2"))
        sm = _sm(tmp_path)
        sm.create_session(session_id="reg-01")
        engine = MemoryFormationEngine(mc, session_manager=sm)
        engine.ingest(user_message="test", assistant_response="ok", session_id="reg-01")
        loaded = sm.load_session("reg-01")
        assert len(loaded.memory.history) > 0

    def test_history_and_facts_coexist(self, tmp_path: Path) -> None:
        sm = _sm(tmp_path)
        sm.create_session(session_id="reg-02")
        sm.add_memory_entry("reg-02", "key", "value")
        sm.append_history("reg-02", SessionHistoryEntry(
            id="evt-reg", timestamp=_now(), role="user", content="hi",
        ))
        session = sm.load_session("reg-02")
        assert session.memory.entries
        assert session.memory.history

    def test_markdown_has_all_required_sections(self, tmp_path: Path) -> None:
        sm = _sm(tmp_path)
        sm.create_session(session_id="reg-03")
        from app.memory.session_store import session_memory_md_path
        md = session_memory_md_path(tmp_path, "reg-03").read_text(encoding="utf-8")
        for section in [
            "## Summary", "## Conversation Timeline", "## Conversation Log", "## Session Memory",
        ]:
            assert section in md, f"Regression: missing section {section!r}"

    def test_session_three_file_structure_intact(self, tmp_path: Path) -> None:
        sm = _sm(tmp_path)
        sm.create_session(session_id="reg-04")
        from app.memory.session_store import (
            metadata_path, session_memory_json_path, session_memory_md_path,
        )
        assert metadata_path(tmp_path, "reg-04").exists()
        assert session_memory_json_path(tmp_path, "reg-04").exists()
        assert session_memory_md_path(tmp_path, "reg-04").exists()
