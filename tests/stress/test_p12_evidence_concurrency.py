"""P12.3 — P8 Evidence Concurrency & Durability Stress Tests.

Tests concurrent evidence emission, sequence uniqueness, correlation integrity,
and evidence store failure handling under load.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.app import create_orchestrator
from app.config.settings import Settings
from app.core.contracts import RoutingDecision, RuntimeContext, TaskStatus
from app.evidence.store import EvidenceStore, EvidenceStoreConfig
from app.evidence.instrumentation import EvidenceInstrumentation
from app.evidence.contracts import EvidenceEvent, EvidencePayload, EvidenceEventType, EvidenceSeverity
from tests.conftest import approved_task


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def evidence_store(tmp_path):
    """Create an isolated evidence store for testing."""
    config = EvidenceStoreConfig(
        db_path=tmp_path / "evidence.db",
        enabled=True,
        retention_days=90,
        max_events_per_execution=10000,
        max_payload_bytes=64000,
    )
    return EvidenceStore(config)


@pytest.fixture
def evidence_instrumentation(evidence_store):
    """Create evidence instrumentation for testing."""
    return EvidenceInstrumentation(evidence_store)


@pytest.fixture
def orchestrator_with_evidence(tmp_path):
    """Create orchestrator with isolated evidence store."""
    settings = Settings(
        _env_file=None,
        sqlite_url=str(tmp_path / "stress.db"),
        personality_state_path=str(tmp_path / "personality.json"),
        checkpoint_location=str(tmp_path / "checkpoints"),
        evidence_db_path=str(tmp_path / "evidence.db"),
        evidence_enabled=True,
    )
    return create_orchestrator(settings)


# ---------------------------------------------------------------------------
# Concurrent Evidence Sequence Tests
# ---------------------------------------------------------------------------

def create_evidence_event(
    execution_id: str,
    event_type: EvidenceEventType,
    principal_id: str,
    session_id: str,
    task_id: str,
    action_id: str,
    retry_attempt: int = 0,
    provider: str = "test",
    model: str = "test-model",
    tool_name: str = None,
    tool_action: str = None,
    severity: EvidenceSeverity = EvidenceSeverity.INFO,
    duration_ms: int = 1,
    status: str = "started",
    failure_type: str = None,
    decision: str = None,
    reason_code: str = None,
    metadata: dict = None,
) -> EvidenceEvent:
    """Create an evidence event with proper payload."""
    payload = EvidencePayload(
        event_type=event_type,
        execution_id=execution_id,
        sequence_number=0,  # Will be assigned by store
        principal_id=principal_id,
        session_id=session_id,
        task_id=task_id,
        action_id=action_id,
        retry_attempt=retry_attempt,
        provider=provider,
        model=model,
        tool_name=tool_name,
        tool_action=tool_action,
        severity=severity,
        duration_ms=duration_ms,
        status=status,
        failure_type=failure_type,
        decision=decision,
        reason_code=reason_code,
        metadata=metadata or {},
    )
    return EvidenceEvent(payload=payload)


def test_threaded_evidence_sequence_allocation_is_atomic(evidence_store):
    """Real overlapping connections cannot allocate duplicate sequences."""
    execution_id = "threaded-sequence-test"

    def append(index: int):
        return evidence_store.append(create_evidence_event(
            execution_id=execution_id,
            event_type=EvidenceEventType.TASK_COMPLETED,
            principal_id="threaded-principal",
            session_id="threaded-session",
            task_id=f"threaded-{index}",
            action_id=f"threaded-{index}",
        ))

    with ThreadPoolExecutor(max_workers=8) as pool:
        events = list(pool.map(append, range(100)))

    sequences = sorted(event.payload.sequence_number for event in events)
    assert sequences == list(range(1, 101))


def test_threaded_evidence_connections_close_for_windows_cleanup(tmp_path):
    """Explicit shutdown releases every worker-owned SQLite handle."""
    db_path = tmp_path / "threaded-close.db"
    store = EvidenceStore(EvidenceStoreConfig(db_path=db_path, enabled=True))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: store.append(create_evidence_event(
            execution_id=f"close-{i}",
            event_type=EvidenceEventType.TASK_COMPLETED,
            principal_id="close-principal",
            session_id="close-session",
            task_id=f"close-{i}",
            action_id=f"close-{i}",
        )), range(100)))

    store.close()
    db_path.unlink()
    assert not db_path.exists()


@pytest.mark.asyncio
async def test_concurrent_evidence_sequences_are_unique(evidence_store):
    """Multiple concurrent emitters must get unique sequence numbers per execution."""
    execution_id = "concurrent-seq-test"
    n_emitters = 10
    events_per_emitter = 10

    async def emit_events(emitter_id):
        for i in range(events_per_emitter):
            event = create_evidence_event(
                execution_id=execution_id,
                event_type=EvidenceEventType.TASK_STARTED,
                principal_id=f"emitter-{emitter_id}",
                session_id="test-session",
                task_id=f"task-{emitter_id}-{i}",
                action_id=f"action-{emitter_id}-{i}",
                metadata={"emitter": emitter_id, "index": i},
            )
            evidence_store.append(event)

    await asyncio.gather(*[emit_events(i) for i in range(n_emitters)])

    # Query all events and verify sequence uniqueness
    conn = sqlite3.connect(str(evidence_store.config.db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        "SELECT sequence_number FROM evidence_events WHERE execution_id = ? ORDER BY sequence_number",
        (execution_id,)
    )
    sequences = [row["sequence_number"] for row in cursor.fetchall()]
    conn.close()

    total_events = n_emitters * events_per_emitter
    assert len(sequences) == total_events, f"Expected {total_events} events, got {len(sequences)}"
    assert len(set(sequences)) == total_events, f"Duplicate sequence numbers: {sequences}"
    # Sequences should be 1..N
    assert sequences == list(range(1, total_events + 1)), f"Non-contiguous sequences: {sequences}"


@pytest.mark.asyncio
async def test_concurrent_evidence_events_not_lost(evidence_store):
    """High-concurrency emission must not lose events."""
    execution_id = "no-loss-test"
    n_emitters = 20
    events_per_emitter = 50

    async def emit_events(emitter_id):
        for i in range(events_per_emitter):
            event = create_evidence_event(
                execution_id=execution_id,
                event_type=EvidenceEventType.TASK_COMPLETED,
                principal_id=f"principal-{emitter_id}",
                session_id="test-session",
                task_id=f"task-{emitter_id}-{i}",
                action_id=f"action-{emitter_id}-{i}",
                status="completed",
                decision="allow",
                metadata={"emitter": emitter_id, "index": i},
            )
            evidence_store.append(event)

    await asyncio.gather(*[emit_events(i) for i in range(n_emitters)])

    conn = sqlite3.connect(str(evidence_store.config.db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        "SELECT COUNT(*) as count FROM evidence_events WHERE execution_id = ?",
        (execution_id,)
    )
    count = cursor.fetchone()["count"]
    conn.close()

    expected = n_emitters * events_per_emitter
    assert count == expected, f"Lost events: expected {expected}, got {count}"


@pytest.mark.asyncio
async def test_evidence_correlation_correct_under_concurrency(evidence_store):
    """Event correlation (execution_id, principal_id, task_id) must remain correct under concurrency."""
    execution_id = "correlation-test"
    n_emitters = 10
    events_per_emitter = 20

    async def emit_events(emitter_id):
        principal_id = f"principal-{emitter_id}"
        for i in range(events_per_emitter):
            task_id = f"task-{emitter_id}-{i}"
            event = create_evidence_event(
                execution_id=execution_id,
                event_type=EvidenceEventType.TOOL_COMPLETED,
                principal_id=principal_id,
                session_id="test-session",
                task_id=task_id,
                action_id=f"action-{task_id}",
                status="completed",
                decision="allow",
                tool_name="test-tool",
                tool_action="execute",
                metadata={"emitter": emitter_id, "index": i},
            )
            evidence_store.append(event)

    await asyncio.gather(*[emit_events(i) for i in range(n_emitters)])

    conn = sqlite3.connect(str(evidence_store.config.db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        "SELECT execution_id, principal_id, task_id FROM evidence_events WHERE execution_id = ?",
        (execution_id,)
    )
    rows = cursor.fetchall()
    conn.close()

    # Verify every row has correct correlation
    for row in rows:
        assert row["execution_id"] == execution_id
        assert row["principal_id"].startswith("principal-")
        assert row["task_id"].startswith("task-")
        # Extract emitter from principal and task
        principal_num = int(row["principal_id"].split("-")[1])
        task_num = int(row["task_id"].split("-")[1])
        assert principal_num == task_num, f"Mismatch: principal {row['principal_id']} vs task {row['task_id']}"


@pytest.mark.asyncio
async def test_evidence_principal_scoping_preserved(evidence_store):
    """Principal boundaries must not leak under concurrent emission."""
    execution_id = "scoping-test"

    async def emit_as_principal(principal_id, count):
        for i in range(count):
            event = create_evidence_event(
                execution_id=execution_id,
                event_type=EvidenceEventType.TASK_STARTED,
                principal_id=principal_id,
                session_id="test-session",
                task_id=f"task-{i}",
                action_id=f"action-{i}",
            )
            evidence_store.append(event)

    # Two principals emitting concurrently
    await asyncio.gather(
        emit_as_principal("principal-a", 50),
        emit_as_principal("principal-b", 50),
    )

    conn = sqlite3.connect(str(evidence_store.config.db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        "SELECT principal_id, COUNT(*) as count FROM evidence_events WHERE execution_id = ? GROUP BY principal_id",
        (execution_id,)
    )
    rows = cursor.fetchall()
    conn.close()

    counts = {row["principal_id"]: row["count"] for row in rows}
    assert counts["principal-a"] == 50
    assert counts["principal-b"] == 50
    assert len(counts) == 2  # No third principal


# ---------------------------------------------------------------------------
# Evidence Write Failure Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evidence_write_failure_does_not_corrupt_execution_truth(orchestrator_with_evidence):
    """Evidence store failure must not rewrite execution success/failure."""
    orchestrator = orchestrator_with_evidence

    # Mock the evidence store append to raise SQLite errors
    original_append = orchestrator_with_evidence.evidence_instrumentation._store.append

    call_count = 0

    def failing_emit(event):
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            raise sqlite3.OperationalError("database is locked")
        return original_append(event)

    orchestrator_with_evidence.evidence_instrumentation._store.append = failing_emit

    try:
        task = approved_task(task_id="sqlite-err", action_type="text_generation", subject_id="sqlite-err")

        result = await orchestrator_with_evidence.runtime.run(
            RuntimeContext(request_id="sqlite-err"),
            task,
            RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="sqlite error test"),
        )

        # Should complete despite evidence failures
        assert result.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}
    finally:
        orchestrator_with_evidence.evidence_instrumentation._store.append = original_append


# ---------------------------------------------------------------------------
# Evidence Retention Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evidence_retention_preserves_active_executions(tmp_path):
    """Retention pruning must preserve evidence for active executions."""
    from datetime import datetime, timedelta

    config = EvidenceStoreConfig(
        db_path=tmp_path / "retention.db",
        enabled=True,
        retention_days=1,  # Short retention for test
        max_events_per_execution=1000,
        max_payload_bytes=64000,
    )
    store = EvidenceStore(config)

    # Add evidence for completed execution (old timestamp) - need to insert into executions table too
    old_time = datetime.utcnow() - timedelta(days=5)

    # Manually insert old execution record (simulating completed execution)
    conn = sqlite3.connect(str(config.db_path))
    conn.execute("""
        INSERT INTO executions
        (execution_id, principal_id, session_id, created_at, updated_at, terminal_at, final_status, request_summary)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, ("old-execution", "test", "session", old_time.isoformat(), old_time.isoformat(), old_time.isoformat(), "completed", "Old execution"))

    # Add evidence for old execution
    conn.execute("""
        INSERT INTO evidence_events
        (execution_id, sequence_number, event_type, principal_id, session_id,
         task_id, action_id, retry_attempt, provider, model, tool_name, tool_action,
         severity, duration_ms, status, failure_type, decision, reason_code,
         metadata_json, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, ("old-execution", 1, "TASK_COMPLETED", "test", "session", "task-1", "action-1",
          0, "test", "test-model", "tool", "execute", "INFO", 10, "completed",
          None, "allow", None, "{}", old_time.isoformat()))
    conn.commit()
    conn.close()

    # Add evidence for active execution (recent timestamp) - need execution record too
    conn = sqlite3.connect(str(config.db_path))
    conn.execute("""
        INSERT INTO executions
        (execution_id, principal_id, session_id, created_at, updated_at, terminal_at, final_status, request_summary)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, ("active-execution", "test", "session", datetime.utcnow().isoformat(), datetime.utcnow().isoformat(), None, "running", "Active execution"))
    conn.commit()
    conn.close()

    event = EvidenceEvent(
        payload=EvidencePayload(
            event_type=EvidenceEventType.TASK_STARTED,
            execution_id="active-execution",
            sequence_number=0,
            principal_id="test",
            session_id="session",
            task_id="task-1",
            action_id="action-1",
            retry_attempt=0,
            provider="test",
            model="test-model",
            tool_name=None,
            tool_action=None,
            severity=EvidenceSeverity.INFO,
            duration_ms=1,
            status="started",
            failure_type=None,
            decision=None,
            reason_code=None,
            metadata={},
        )
    )
    store.append(event)

    # Run retention (would normally be called periodically)
    store.cleanup_retention()

    # Old execution should be pruned, active preserved
    conn = sqlite3.connect(str(config.db_path))
    cursor = conn.execute("SELECT execution_id FROM evidence_events")
    remaining = {row[0] for row in cursor.fetchall()}
    conn.close()

    assert "old-execution" not in remaining
    assert "active-execution" in remaining


# ---------------------------------------------------------------------------
# Query Bounds Under Load
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evidence_query_bounds_hold_under_load(evidence_store):
    """Query limits must be enforced even under high event volume."""
    execution_id = "query-bounds-test"

    # Insert many events
    for i in range(2000):
        event = create_evidence_event(
            execution_id=execution_id,
            event_type=EvidenceEventType.TASK_STARTED,
            principal_id="test",
            session_id="session",
            task_id=f"task-{i}",
            action_id=f"action-{i}",
        )
        evidence_store.append(event)

    # Query with limit
    events = evidence_store.get_execution_events(execution_id=execution_id, limit=100)
    assert len(events) == 100, "Query limit not enforced"

    # Query with offset
    events = evidence_store.get_execution_events(execution_id=execution_id, limit=50, start_after_sequence=100)
    assert len(events) == 50, "Query offset not enforced"
    assert events[0].sequence_number == 101


# ---------------------------------------------------------------------------
# SQLite Integrity Under Load
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sqlite_integrity_under_concurrent_writes(evidence_store):
    """Database must remain valid under concurrent writes."""
    execution_id = "integrity-test"
    n_writers = 10
    events_per_writer = 100

    async def write_events(writer_id):
        for i in range(events_per_writer):
            event = create_evidence_event(
                execution_id=execution_id,
                event_type=EvidenceEventType.TOOL_COMPLETED,
                principal_id=f"principal-{writer_id}",
                session_id="session",
                task_id=f"task-{writer_id}-{i}",
                action_id=f"action-{i}",
                status="completed",
                decision="allow",
                tool_name="tool",
                tool_action="execute",
                metadata={"writer": writer_id},
            )
            evidence_store.append(event)

    await asyncio.gather(*[write_events(i) for i in range(n_writers)])

    # Verify database integrity
    conn = sqlite3.connect(str(evidence_store.config.db_path))
    # Check no constraint violations
    cursor = conn.execute("PRAGMA integrity_check")
    result = cursor.fetchone()[0]
    conn.close()

    assert result == "ok", f"Database integrity check failed: {result}"


# ---------------------------------------------------------------------------
# Orchestrator-Level Evidence Stress
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evidence_instrumentation_concurrent_execution(evidence_instrumentation):
    """EvidenceInstrumentation must produce correct evidence under concurrent executions.

    This test uses EvidenceInstrumentation directly to emit execution lifecycle
    events, simulating what the orchestrator would do with full evidence integration.
    """
    n = 8
    instrumentation = evidence_instrumentation

    async def execute_with_evidence(i: int):
        """Execute a task and emit evidence for it."""
        exec_id = f"orch-evidence-{i}"

        # Emit execution created event
        instrumentation.execution_created(
            execution_id=exec_id,
            principal_id=f"principal-{i}",
            session_id=f"session-{i}",
            request=f"Test request {i}",
        )

        # Simulate work
        await asyncio.sleep(0.01)

        # Emit completion event
        instrumentation.execution_completed(
            execution_id=exec_id,
            principal_id=f"principal-{i}",
            session_id=f"session-{i}",
            duration_ms=100,
        )

    # Run concurrent executions with evidence
    await asyncio.gather(*[execute_with_evidence(i) for i in range(n)])

    # Verify evidence was produced for each execution
    conn = sqlite3.connect(str(evidence_instrumentation._store.config.db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        "SELECT execution_id, COUNT(*) as count FROM evidence_events GROUP BY execution_id"
    )
    counts = {row["execution_id"]: row["count"] for row in cursor.fetchall()}
    conn.close()

    # Each execution should have at least 2 events (created + completed)
    for i in range(n):
        exec_id = f"orch-evidence-{i}"
        assert exec_id in counts, f"Missing evidence for {exec_id}"
        assert counts[exec_id] >= 2, f"Expected at least 2 events for {exec_id}, got {counts[exec_id]}"
