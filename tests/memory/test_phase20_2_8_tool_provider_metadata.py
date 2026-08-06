import pytest
from types import SimpleNamespace
from typing import Any
import datetime

from app.memory.formation.session_builder import SessionBuilder
from app.memory.session_models import SessionHistoryEntry, SessionMetadata
from app.core.contracts.runtime import RuntimeResult
from app.core.contracts.planning import TaskStatus
from app.core.contracts.routing import RoutingDecision

def test_tool_metadata_extraction():
    # Simulate a tool execution result as wrapped by workflow engine
    tool_result = RuntimeResult(
        task_id="t1",
        status=TaskStatus.COMPLETED,
        output={},
        metadata={
            "runtime_action_type": "tool",
            "tool": "filesystem",
            "action": "write",
            "args": {"path": "/tmp/test.py"}
        }
    )

    report = SimpleNamespace(
        plan_id="plan_123",
        started_at="2026-08-04T10:42:00+00:00",
        executed_tasks=["t1"],
        tool_results=[tool_result.model_dump()],
        provider_results=[],
        execution_state=SimpleNamespace(value="succeeded"),
        errors=[]
    )

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    metadata = SessionMetadata(session_id="test_1", created_at=now, updated_at=now)
    entries = SessionBuilder.build_history_entries(
        user_message="Do it",
        assistant_response="Done",
        execution_report=report,
        base_turn_number=1,
    )
    SessionBuilder.update_metadata(metadata, entries, execution_report=report)

    assert "filesystem" in metadata.tools_used
    assert "/tmp/test.py" in metadata.files_created
    assert "/tmp/test.py" not in metadata.files_modified
    
    # NEW ASSERTIONS for SessionHistoryEntry metadata extraction
    assert "filesystem" in entries[1].tool_calls
    
def test_provider_metadata_extraction():
    provider_result = RuntimeResult(
        task_id="t2",
        status=TaskStatus.COMPLETED,
        routing=RoutingDecision(
            provider_id="openai",
            model_id="gpt-4o",
            reasoning_summary="default"
        ),
        output={},
        metadata={
            "runtime_action_type": "text_generation"
        }
    )

    report = SimpleNamespace(
        plan_id="plan_124",
        started_at="2026-08-04T10:42:00+00:00",
        executed_tasks=["t2"],
        tool_results=[],
        provider_results=[provider_result.model_dump()],
        execution_state=SimpleNamespace(value="succeeded"),
        errors=[]
    )

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    metadata = SessionMetadata(session_id="test_2", created_at=now, updated_at=now)
    entries = SessionBuilder.build_history_entries(
        user_message="Hello",
        assistant_response="Hi",
        execution_report=report,
        base_turn_number=1,
    )
    SessionBuilder.update_metadata(metadata, entries, execution_report=report)

    assert "openai" in metadata.providers_used
    assert metadata.tools_used == []
    
    # NEW ASSERTIONS for SessionHistoryEntry metadata extraction
    assert entries[1].provider == "openai"

