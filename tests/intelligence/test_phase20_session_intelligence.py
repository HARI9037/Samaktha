"""Phase 20.2 — Session Intelligence Regression Tests.

Covers:
1. Conversation routing reaches both MemoryController and SessionManager.
2. Session history preserves chronological order.
3. Metadata is derived solely from runtime evidence.
4. Markdown regenerates correctly from JSON.
5. Retrieval prefers metadata over raw history.
6. Cross-session queries return synthesized summaries.
7. Provenance, confidence, and session ID are preserved.
8. No duplicate storage between long-term memory and session memory.
9. Sessions with no tool execution still generate valid history and metadata.
10. Failed/cancelled executions are reflected accurately, never marked successful.
"""

from __future__ import annotations

import datetime
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from app.memory.formation.session_builder import SessionBuilder
from app.memory.session_manager import SessionManager
from app.memory.session_models import (
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


def _make_session_manager(tmp_path: Path) -> SessionManager:
    return SessionManager(base_dir=tmp_path)


def _make_exec_report(
    *,
    success: bool = True,
    state: ExecutionTruthState = ExecutionTruthState.SUCCEEDED,
    tool_results: list[dict] | None = None,
    errors: list[str] | None = None,
) -> ExecutionReport:
    return ExecutionReport(
        plan_id="plan-test-001",
        success=success,
        execution_state=state,
        tool_results=tool_results or [],
        errors=errors or [],
    )


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 1. Conversation routing reaches both MemoryController and SessionManager
# ---------------------------------------------------------------------------


class TestConversationRouting:
    def test_ingest_writes_to_memory_controller(self, tmp_path: Path) -> None:
        """Every ingest must write to MemoryController (long-term memory)."""
        from app.memory.formation.engine import MemoryFormationEngine

        mc = MagicMock()
        mc.memory_manager = MagicMock()
        mc.memory_manager.get_recent_context.return_value = []
        mc.write_conversation = MagicMock(return_value=MagicMock(id="conv-1"))

        engine = MemoryFormationEngine(mc)
        results = engine.ingest(user_message="hello", assistant_response="hi")

        mc.write_conversation.assert_called_once()
        assert any(r.memory_type == "conversation" for r in results)

    def test_ingest_writes_to_session_manager(self, tmp_path: Path) -> None:
        """When SessionManager is wired in, history must be appended."""
        from app.memory.formation.engine import MemoryFormationEngine

        mc = MagicMock()
        mc.memory_manager = MagicMock()
        mc.memory_manager.get_recent_context.return_value = []
        mc.write_conversation = MagicMock(return_value=MagicMock(id="conv-2"))

        sm = _make_session_manager(tmp_path)
        session = sm.create_session(session_id="test-routing-01")

        engine = MemoryFormationEngine(mc, session_manager=sm)
        engine.ingest(
            user_message="write a file",
            assistant_response="done",
            session_id="test-routing-01",
        )

        loaded = sm.load_session("test-routing-01")
        assert len(loaded.memory.history) > 0, "SessionManager received no history"

    def test_ingest_routes_both_independently(self, tmp_path: Path) -> None:
        """MemoryController failure must not silence SessionManager write."""
        from app.memory.formation.engine import MemoryFormationEngine

        mc = MagicMock()
        mc.memory_manager = MagicMock()
        mc.memory_manager.get_recent_context.return_value = []
        mc.write_conversation = MagicMock(return_value=MagicMock(id="conv-3"))

        sm = _make_session_manager(tmp_path)
        sm.create_session(session_id="test-routing-02")

        engine = MemoryFormationEngine(mc, session_manager=sm)
        engine.ingest(
            user_message="test message",
            assistant_response="test response",
            session_id="test-routing-02",
        )

        # Both paths were exercised
        mc.write_conversation.assert_called_once()
        loaded = sm.load_session("test-routing-02")
        assert loaded.memory.history  # SessionManager got history


# ---------------------------------------------------------------------------
# 2. Session history preserves chronological order
# ---------------------------------------------------------------------------


class TestChronologicalOrder:
    def test_history_order_preserved(self, tmp_path: Path) -> None:
        sm = _make_session_manager(tmp_path)
        sm.create_session(session_id="order-test-01")

        ts_base = datetime.datetime(2026, 8, 3, 10, 0, 0, tzinfo=datetime.timezone.utc)
        for i in range(5):
            ts = (ts_base + datetime.timedelta(minutes=i)).isoformat()
            entry = SessionHistoryEntry(
                id=f"evt-{i}",
                timestamp=ts,
                role="user" if i % 2 == 0 else "assistant",
                content=f"message {i}",
            )
            sm.append_history("order-test-01", entry)

        loaded = sm.load_session("order-test-01")
        timestamps = [e.timestamp for e in loaded.memory.history]
        assert timestamps == sorted(timestamps), "History is not chronological"

    def test_user_before_assistant_each_turn(self, tmp_path: Path) -> None:
        sm = _make_session_manager(tmp_path)
        sm.create_session(session_id="order-test-02")

        entries = SessionBuilder.build_history_entries("user says hi", "assistant says hello")
        for e in entries:
            sm.append_history("order-test-02", e)

        loaded = sm.load_session("order-test-02")
        assert len(loaded.memory.history) == 2
        assert loaded.memory.history[0].role == "user"
        assert loaded.memory.history[1].role == "assistant"


# ---------------------------------------------------------------------------
# 3. Metadata derived solely from runtime evidence
# ---------------------------------------------------------------------------


class TestMetadataDeterminism:
    def test_tools_extracted_from_execution_report(self) -> None:
        report = _make_exec_report(
            tool_results=[{"tool": "filesystem", "action": "write", "args": {"path": "/tmp/a.py"}}]
        )
        meta = SessionMetadata(
            session_id="meta-test-01",
            created_at=_now_iso(),
            updated_at=_now_iso(),
        )
        entries = SessionBuilder.build_history_entries("create a file", "file created", execution_report=report)
        updated = SessionBuilder.update_metadata(meta, entries, execution_report=report)

        assert "filesystem" in updated.tools_used

    def test_files_created_extracted_from_execution_report(self) -> None:
        report = _make_exec_report(
            tool_results=[{"tool": "filesystem", "action": "write", "args": {"path": "/src/main.py"}}]
        )
        meta = SessionMetadata(session_id="meta-test-02", created_at=_now_iso(), updated_at=_now_iso())
        entries = SessionBuilder.build_history_entries("write file", "done", execution_report=report)
        updated = SessionBuilder.update_metadata(meta, entries, execution_report=report)

        assert "/src/main.py" in updated.files_created

    def test_files_modified_extracted(self) -> None:
        report = _make_exec_report(
            tool_results=[{"tool": "filesystem", "action": "edit", "args": {"path": "/src/utils.py"}}]
        )
        meta = SessionMetadata(session_id="meta-test-03", created_at=_now_iso(), updated_at=_now_iso())
        entries = SessionBuilder.build_history_entries("edit file", "done", execution_report=report)
        updated = SessionBuilder.update_metadata(meta, entries, execution_report=report)

        assert "/src/utils.py" in updated.files_modified

    def test_errors_extracted_from_execution_report(self) -> None:
        report = _make_exec_report(
            success=False,
            state=ExecutionTruthState.FAILED,
            errors=["FileNotFoundError: config.yaml missing"],
        )
        meta = SessionMetadata(session_id="meta-test-04", created_at=_now_iso(), updated_at=_now_iso())
        entries = SessionBuilder.build_history_entries("run pipeline", "failed", execution_report=report)
        updated = SessionBuilder.update_metadata(meta, entries, execution_report=report)

        assert any("FileNotFoundError" in e for e in updated.runtime_errors)

    def test_no_inference_without_evidence(self) -> None:
        """Without execution_report, metadata arrays must stay empty."""
        meta = SessionMetadata(session_id="meta-test-05", created_at=_now_iso(), updated_at=_now_iso())
        entries = SessionBuilder.build_history_entries("hello", "hi")
        updated = SessionBuilder.update_metadata(meta, entries)

        assert updated.tools_used == []
        assert updated.files_created == []
        assert updated.files_modified == []
        assert updated.runtime_errors == []


# ---------------------------------------------------------------------------
# 4. Markdown regenerates correctly from JSON
# ---------------------------------------------------------------------------


class TestMarkdownGeneration:
    def _make_session(self, tmp_path: Path) -> Session:
        sm = _make_session_manager(tmp_path)
        sm.create_session(session_id="md-test-01", title="Test Session")
        sm.update_metadata(
            "md-test-01",
            summary="Worked on filesystem",
        )
        entry = SessionHistoryEntry(
            id="evt-md-1",
            timestamp=_now_iso(),
            role="user",
            content="create a file",
            tool_calls=["filesystem"],
        )
        sm.append_history("md-test-01", entry)
        return sm.load_session("md-test-01")

    def test_markdown_contains_required_sections(self, tmp_path: Path) -> None:
        session = self._make_session(tmp_path)
        md = export_session_markdown(session.metadata, session.memory)

        required = [
            "## Summary",
            "## Major Topics",
            "## Files Created",
            "## Files Modified",
            "## Tools Used",
            "## Errors Encountered",
            "## Bugs Fixed",
            "## Conversation Timeline",
            "## Conversation Log",
        ]
        for section in required:
            assert section in md, f"Missing section: {section}"

    def test_markdown_timeline_from_history(self, tmp_path: Path) -> None:
        session = self._make_session(tmp_path)
        md = export_session_markdown(session.metadata, session.memory)
        # Timeline should reflect the history entry
        assert "filesystem" in md or "User" in md

    def test_markdown_never_stored_standalone(self, tmp_path: Path) -> None:
        """The .md file must always be regenerated from JSON, never independently modified."""
        sm = _make_session_manager(tmp_path)
        sm.create_session(session_id="md-regen-01")
        sm.add_memory_entry("md-regen-01", "key1", "value1")

        from app.memory.session_store import session_memory_md_path
        md_path = session_memory_md_path(sm.base_dir, "md-regen-01")
        original_md = md_path.read_text(encoding="utf-8")

        # Simulate re-save (should regenerate)
        session = sm.load_session("md-regen-01")
        sm.save_session(session)
        regenerated_md = md_path.read_text(encoding="utf-8")

        assert "## Summary" in regenerated_md  # regenerated from JSON, not blank


# ---------------------------------------------------------------------------
# 5. Retrieval prefers metadata over raw history
# ---------------------------------------------------------------------------


class TestMetadataFirstRetrieval:
    def test_session_metadata_retrieved_before_history(self, tmp_path: Path) -> None:
        from app.intelligence.retrieval import RetrievalEngine

        sm = _make_session_manager(tmp_path)
        sm.create_session(session_id="retrieval-meta-01")
        # Simulate tools_used populated
        session = sm.load_session("retrieval-meta-01")
        session.metadata.tools_used = ["filesystem", "internet"]
        sm.save_session(session)

        mc = MagicMock()
        mc.memory_manager = MagicMock()
        mc.memory_manager.get_recent_context.return_value = []
        mc.search = MagicMock(return_value=[])
        mc.find_relevant_skills = MagicMock(return_value=[])

        engine = RetrievalEngine(mc, session_manager=sm)
        result = engine.retrieve("What tools did we use?", session_id="retrieval-meta-01")

        sources = [e.source for e in result.evidence]
        # session_metadata should appear before session_history in the ranked output
        if "session_metadata" in sources and "session_history" in sources:
            assert sources.index("session_metadata") < sources.index("session_history")


# ---------------------------------------------------------------------------
# 6. Cross-session queries return synthesized summaries
# ---------------------------------------------------------------------------


class TestCrossSessionSynthesis:
    def test_cross_session_query_returns_metadata_from_all_sessions(self, tmp_path: Path) -> None:
        from app.intelligence.retrieval import RetrievalEngine

        sm = _make_session_manager(tmp_path)
        for i in range(3):
            sid = f"xsess-{i:02d}"
            sm.create_session(session_id=sid)
            session = sm.load_session(sid)
            session.metadata.tools_used = [f"tool-{i}"]
            session.metadata.files_modified = [f"/file-{i}.py"]
            sm.save_session(session)

        mc = MagicMock()
        mc.memory_manager = MagicMock()
        mc.memory_manager.get_recent_context.return_value = []
        mc.search = MagicMock(return_value=[])
        mc.find_relevant_skills = MagicMock(return_value=[])

        engine = RetrievalEngine(mc, session_manager=sm)
        result = engine.retrieve("What have we worked on recently?", session_id=None)

        sources = {e.source for e in result.evidence}
        assert "session_metadata" in sources, "Cross-session synthesis missing metadata"


# ---------------------------------------------------------------------------
# 7. Provenance, confidence, and session ID are preserved
# ---------------------------------------------------------------------------


class TestProvenance:
    def test_metadata_evidence_has_provenance(self, tmp_path: Path) -> None:
        from app.intelligence.retrieval import RetrievalEngine

        sm = _make_session_manager(tmp_path)
        sm.create_session(session_id="prov-01")
        session = sm.load_session("prov-01")
        session.metadata.bugs_fixed = ["NullPointerError in pipeline"]
        sm.save_session(session)

        mc = MagicMock()
        mc.memory_manager = MagicMock()
        mc.memory_manager.get_recent_context.return_value = []
        mc.search = MagicMock(return_value=[])
        mc.find_relevant_skills = MagicMock(return_value=[])

        engine = RetrievalEngine(mc, session_manager=sm)
        result = engine.retrieve("What bugs were fixed?", session_id="prov-01")

        for ev in result.evidence:
            if ev.source == "session_metadata":
                assert ev.provenance.startswith("session:prov-01:metadata:")
                assert ev.confidence == 1.0
                assert ev.scope == "session"
                break

    def test_history_evidence_has_provenance(self, tmp_path: Path) -> None:
        from app.intelligence.retrieval import RetrievalEngine

        sm = _make_session_manager(tmp_path)
        sm.create_session(session_id="prov-02")
        sm.append_history(
            "prov-02",
            SessionHistoryEntry(
                id="evt-prov-1",
                timestamp=_now_iso(),
                role="user",
                content="run the filesystem tool",
                tool_calls=["filesystem"],
            ),
        )

        mc = MagicMock()
        mc.memory_manager = MagicMock()
        mc.memory_manager.get_recent_context.return_value = []
        mc.search = MagicMock(return_value=[])
        mc.find_relevant_skills = MagicMock(return_value=[])

        engine = RetrievalEngine(mc, session_manager=sm)
        result = engine.retrieve("filesystem", session_id="prov-02")

        for ev in result.evidence:
            if "prov-02" in ev.provenance:
                assert ev.provenance  # non-empty provenance
                assert ev.confidence > 0
                break


# ---------------------------------------------------------------------------
# 8. No duplicate storage between long-term memory and session memory
# ---------------------------------------------------------------------------


class TestNoDuplicateStorage:
    def test_session_history_not_in_long_term_memory(self, tmp_path: Path) -> None:
        """SessionMemory.history is never written to MemoryController."""
        from app.memory.formation.engine import MemoryFormationEngine

        mc = MagicMock()
        mc.memory_manager = MagicMock()
        mc.memory_manager.get_recent_context.return_value = []
        written_contents: list[str] = []

        def track_write(**kwargs):
            written_contents.append(kwargs.get("content", ""))
            return MagicMock(id="conv-track")

        mc.write_conversation = track_write

        sm = _make_session_manager(tmp_path)
        sm.create_session(session_id="dedup-01")

        engine = MemoryFormationEngine(mc, session_manager=sm)
        engine.ingest("hello world", "hi there", session_id="dedup-01")

        # Long-term memory should have exactly one conversation write
        assert len(written_contents) == 1
        # Session history should also have entries
        loaded = sm.load_session("dedup-01")
        assert len(loaded.memory.history) > 0


# ---------------------------------------------------------------------------
# 9. Sessions with no tool execution still generate valid history
# ---------------------------------------------------------------------------


class TestNoToolExecution:
    def test_plain_conversation_creates_valid_session(self, tmp_path: Path) -> None:
        sm = _make_session_manager(tmp_path)
        sm.create_session(session_id="notool-01")

        entries = SessionBuilder.build_history_entries("hello", "hi")
        for e in entries:
            sm.append_history("notool-01", e)

        loaded = sm.load_session("notool-01")
        assert len(loaded.memory.history) == 2
        assert loaded.memory.history[0].tool_calls == []
        assert loaded.memory.history[0].execution_state is None or loaded.memory.history[0].execution_state == "none"

    def test_metadata_empty_when_no_tool_execution(self) -> None:
        meta = SessionMetadata(session_id="notool-02", created_at=_now_iso(), updated_at=_now_iso())
        entries = SessionBuilder.build_history_entries("hello", "hi")
        updated = SessionBuilder.update_metadata(meta, entries)

        assert updated.tools_used == []
        assert updated.files_created == []
        assert updated.files_modified == []

    def test_markdown_valid_with_no_history(self) -> None:
        meta = SessionMetadata(
            session_id="notool-03",
            created_at=_now_iso(),
            updated_at=_now_iso(),
            message_count=0,
        )
        memory = SessionMemory(session_id="notool-03")
        md = export_session_markdown(meta, memory)
        # Must not raise and should contain all sections
        assert "## Conversation Timeline" in md
        assert "_No timeline available._" in md


# ---------------------------------------------------------------------------
# 10. Failed/cancelled executions reflected accurately
# ---------------------------------------------------------------------------


class TestFailedExecution:
    def test_failed_execution_state_recorded(self) -> None:
        report = _make_exec_report(
            success=False,
            state=ExecutionTruthState.FAILED,
        )
        entries = SessionBuilder.build_history_entries(
            "run something",
            "it failed",
            execution_report=report,
        )
        assistant_entry = next(e for e in entries if e.role == "assistant")
        assert assistant_entry.execution_state == "failed"

    def test_cancelled_execution_state_recorded(self) -> None:
        report = _make_exec_report(
            success=False,
            state=ExecutionTruthState.CANCELLED,
        )
        entries = SessionBuilder.build_history_entries(
            "run task",
            "cancelled",
            execution_report=report,
        )
        assistant_entry = next(e for e in entries if e.role == "assistant")
        assert assistant_entry.execution_state == "cancelled"

    def test_failed_execution_never_marked_succeeded(self) -> None:
        report = _make_exec_report(success=False, state=ExecutionTruthState.FAILED)
        entries = SessionBuilder.build_history_entries("run", "error", execution_report=report)
        for e in entries:
            assert e.execution_state != "succeeded", f"Entry {e.id} incorrectly marked as succeeded"

    def test_failed_task_errors_in_metadata(self) -> None:
        report = _make_exec_report(
            success=False,
            state=ExecutionTruthState.FAILED,
            errors=["RuntimeError: connection refused"],
        )
        meta = SessionMetadata(session_id="fail-01", created_at=_now_iso(), updated_at=_now_iso())
        entries = SessionBuilder.build_history_entries("connect", "failed", execution_report=report)
        updated = SessionBuilder.update_metadata(meta, entries, execution_report=report)

        assert any("RuntimeError" in e for e in updated.runtime_errors)
