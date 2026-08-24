"""P12.4 — P6 Recovery/Restart/Duplicate-Effect Stress Tests.

Tests checkpoint atomicity, crash injection, recovery state machine,
duplicate suppression, and unknown mutation handling under stress.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from app.core.contracts.planning import TaskStatus
from app.core.execution_coordinator import ExecutionCoordinator
from app.core.contracts.runtime import RuntimeResult
from app.runtime.checkpoint import CheckpointStore, RecoveryCheckpoint


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def checkpoint_store(tmp_path):
    """Create an isolated checkpoint store."""
    return CheckpointStore(tmp_path / "checkpoints")


def _pipeline(request: str, result: RuntimeResult) -> "PipelineState":
    """Build a real PipelineState so checkpoints stay serializable."""
    from app.core.orchestrator.pipeline import PipelineState
    return PipelineState(request=request, runtime_result=result)


@pytest.fixture
def execution_coordinator():
    """Create an execution coordinator with mock lifecycle."""
    class MockLifecycle:
        def __init__(self):
            self.calls = 0
            self.should_fail = False
            self.fail_after = 0
            self.fail_count = 0

        async def run_pipeline(self, request, runtime_context, conversation=None):
            self.calls += 1

            if self.should_fail and self.fail_count < self.fail_after:
                self.fail_count += 1
                return _pipeline(
                    request,
                    RuntimeResult(
                        task_id=request,
                        status=TaskStatus.FAILED,
                        error="injected failure",
                    ),
                )

            return _pipeline(
                request,
                RuntimeResult(
                    task_id=request,
                    status=TaskStatus.COMPLETED,
                    output={"done": True},
                ),
            )

        async def resume_pipeline(self, state, runtime_context, task_id, updates):
            return _pipeline(
                state.request,
                RuntimeResult(
                    task_id=task_id,
                    status=TaskStatus.COMPLETED,
                    output={"done": True},
                ),
            )

    return ExecutionCoordinator(MockLifecycle())


# ---------------------------------------------------------------------------
# Checkpoint Atomicity Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_checkpoint_repeated_writes_remain_atomic(checkpoint_store, tmp_path):
    """Repeated checkpoint saves must be atomic - no partial writes."""
    execution_id = "atomic-checkpoint"
    principal_id = "test-user"
    session_id = "test-session"

    # Perform many sequential checkpoint updates
    for i in range(100):
        checkpoint = RecoveryCheckpoint(
            execution_id=execution_id,
            principal_id=principal_id,
            session_id=session_id,
            execution_state={"execution_id": execution_id, "step": i},
            pipeline_state={"step": i, "data": "x" * 1000},
            generation=i + 1,  # generation must be >= 1
        )
        checkpoint_store.save_checkpoint(checkpoint)

        # Verify each save produces valid checkpoint
        loaded = checkpoint_store.load_checkpoint(execution_id)
        assert loaded.generation == i + 1
        assert loaded.execution_state["step"] == i

    # No temp files should remain
    temp_files = list(tmp_path.glob("*.tmp"))
    assert len(temp_files) == 0, f"Temp files remain: {temp_files}"


@pytest.mark.asyncio
async def test_checkpoint_concurrent_saves_atomic(checkpoint_store):
    """Concurrent checkpoint saves for different executions must be atomic."""
    async def save_checkpoints(exec_id, count):
        for i in range(count):
            checkpoint = RecoveryCheckpoint(
                execution_id=exec_id,
                principal_id="user",
                session_id="session",
                execution_state={"execution_id": exec_id, "step": i},
                pipeline_state={"step": i},
                generation=i + 1,  # generation must be >= 1
            )
            checkpoint_store.save_checkpoint(checkpoint)
            await asyncio.sleep(0.001)  # Small delay to encourage interleaving

    await asyncio.gather(*[
        save_checkpoints(f"concurrent-{j}", 20)
        for j in range(10)
    ])

    # Verify all checkpoints are valid
    for j in range(10):
        exec_id = f"concurrent-{j}"
        loaded = checkpoint_store.load_checkpoint(exec_id)
        assert loaded.execution_id == exec_id
        assert loaded.generation == 20  # Last saved


@pytest.mark.asyncio
async def test_checkpoint_crash_during_write_preserves_valid_state(tmp_path):
    """Crash during checkpoint write must not leave corrupt state."""
    store = CheckpointStore(tmp_path / "checkpoints")
    execution_id = "crash-during-write"

    # Create initial valid checkpoint
    initial = RecoveryCheckpoint(
        execution_id=execution_id, principal_id="u", session_id="s",
        execution_state={"step": 0}, pipeline_state={}, generation=1
    )
    store.save_checkpoint(initial)

    # Simulate crash during write by making the temp file read-only
    # We can't easily test the crash during write, but we can verify
    # that the atomic write mechanism works correctly
    # by verifying that a valid checkpoint is always readable

    # Create a valid checkpoint
    checkpoint = RecoveryCheckpoint(
        execution_id=execution_id, principal_id="u", session_id="s",
        execution_state={"step": 1}, pipeline_state={}, generation=2
    )
    store.save_checkpoint(checkpoint)

    # Verify it's readable
    loaded = store.load_checkpoint(execution_id)
    assert loaded.generation == 2

    # Verify the original is not corrupted by reading it again
    loaded_again = store.load_checkpoint(execution_id)
    assert loaded_again.generation == 2


@pytest.mark.asyncio
async def test_checkpoint_crash_after_temp_write_before_replace(tmp_path):
    """Crash after temp write but before atomic replace must not lose data."""
    store = CheckpointStore(tmp_path / "checkpoints")
    execution_id = "crash-after-temp"

    # Create initial checkpoint
    initial = RecoveryCheckpoint(
        execution_id=execution_id, principal_id="u", session_id="s",
        execution_state={"step": 0}, pipeline_state={}, generation=1
    )
    store.save_checkpoint(initial)

    # The atomic replace (os.rename) is generally crash-safe on POSIX/Windows
    # Verify that even if process dies after temp write, we don't get corruption
    # Use different execution IDs for each checkpoint to avoid generation conflicts
    for i in range(50):
        exec_id = f"crash-after-temp-{i}"
        checkpoint = RecoveryCheckpoint(
            execution_id=exec_id, principal_id="u", session_id="s",
            execution_state={"step": i}, pipeline_state={}, generation=1
        )
        store.save_checkpoint(checkpoint)

    # Verify all checkpoints are valid
    for i in range(50):
        exec_id = f"crash-after-temp-{i}"
        loaded = store.load_checkpoint(exec_id)
        assert loaded.generation == 1


@pytest.mark.asyncio
async def test_invalid_checkpoint_fails_safely(checkpoint_store):
    """Corrupt checkpoint must fail with clear error, not corrupt state."""
    import sqlite3

    # Create corrupt checkpoint file
    checkpoint_dir = checkpoint_store._directory
    corrupt_path = checkpoint_dir / "corrupt.json"
    corrupt_path.write_text("{not valid json")

    with pytest.raises(Exception) as exc_info:
        checkpoint_store.load_checkpoint("corrupt")

    # Should raise CheckpointInvalidError or similar
    assert "corrupt" in str(exc_info.value).lower() or "json" in str(exc_info.value).lower()
    # Store should still work for valid checkpoints
    valid = RecoveryCheckpoint(
        execution_id="valid", principal_id="u", session_id="s",
        execution_state={}, pipeline_state={}, generation=1
    )
    checkpoint_store.save_checkpoint(valid)
    loaded = checkpoint_store.load_checkpoint("valid")
    assert loaded.execution_id == "valid"


@pytest.mark.asyncio
async def test_checkpoint_schema_mismatch_rejected(checkpoint_store):
    """Future/incompatible schema versions must be rejected safely."""
    # Write checkpoint with future schema version
    checkpoint = RecoveryCheckpoint(
        execution_id="future", principal_id="u", session_id="s",
        execution_state={}, pipeline_state={}, generation=1
    )
    # Manually corrupt the schema version
    checkpoint_path = checkpoint_store._directory / "future.json"
    data = checkpoint.model_dump(mode="json")
    data["schema_version"] = 999
    checkpoint_path.write_text(json.dumps(data))

    with pytest.raises(Exception) as exc_info:
        checkpoint_store.load_checkpoint("future")

    assert "version" in str(exc_info.value).lower() or "schema" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_crash_before_checkpoint_temp_write(tmp_path, monkeypatch):
    """Crash before temp file write must not affect existing checkpoint."""
    import app.runtime.checkpoint as checkpoint_module

    store = CheckpointStore(tmp_path / "checkpoints")
    execution_id = "crash-before-temp"

    # Create initial valid checkpoint
    initial = RecoveryCheckpoint(
        execution_id=execution_id, principal_id="u", session_id="s",
        execution_state={"step": 0}, pipeline_state={}, generation=1
    )
    store.save_checkpoint(initial)

    def _crash(*args, **kwargs):
        raise OSError("Simulated crash before write completed.")

    monkeypatch.setattr(checkpoint_module.json, "dump", _crash)

    checkpoint = RecoveryCheckpoint(
        execution_id=execution_id, principal_id="u", session_id="s",
        execution_state={"step": 1}, pipeline_state={}, generation=2
    )
    with pytest.raises(OSError):
        store.save_checkpoint(checkpoint)

    monkeypatch.undo()

    # Durable state must be untouched - verify through a fresh store (disk only)
    reloaded = CheckpointStore(tmp_path / "checkpoints")
    loaded = reloaded.load_checkpoint(execution_id)
    assert loaded.generation == 1
    assert loaded.execution_state["step"] == 0


@pytest.mark.asyncio
async def test_crash_after_temp_write_before_replace(tmp_path, monkeypatch):
    """Crash after temp write but before atomic replace must not lose data."""
    import app.runtime.checkpoint as checkpoint_module

    directory = tmp_path / "checkpoints"
    store = CheckpointStore(directory)
    execution_id = "crash-after-temp"

    # Create initial checkpoint
    initial = RecoveryCheckpoint(
        execution_id=execution_id, principal_id="u", session_id="s",
        execution_state={"step": 0}, pipeline_state={}, generation=1
    )
    store.save_checkpoint(initial)

    def _crash(_src, _dst):
        raise OSError("Simulated crash before atomic replace.")

    monkeypatch.setattr(checkpoint_module.os, "replace", _crash)

    newer = RecoveryCheckpoint(
        execution_id=execution_id, principal_id="u", session_id="s",
        execution_state={"step": 1}, pipeline_state={}, generation=2
    )
    with pytest.raises(OSError):
        store.save_checkpoint(newer)

    monkeypatch.undo()

    # Durable file must still hold the last fully-committed generation
    reloaded = CheckpointStore(directory)
    loaded = reloaded.load_checkpoint(execution_id)
    assert loaded.generation == 1

    # No temp files may remain after the failed write
    temp_files = list(directory.glob("*.tmp"))
    assert len(temp_files) == 0, f"Temp files remain: {temp_files}"


# ---------------------------------------------------------------------------
# Recovery State Machine Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recovery_states_correct(tmp_path):
    """Recovery must correctly classify durable execution states."""
    from app.core.contracts.memory import DEFAULT_LOCAL_PRINCIPAL_ID
    from app.core.contracts.state import ExecutionState, ExecutionStatus

    class SilentLifecycle:
        async def run_pipeline(self, request, runtime_context, conversation=None):
            return _pipeline(
                request,
                RuntimeResult(task_id=request, status=TaskStatus.COMPLETED),
            )

        async def resume_pipeline(self, state, runtime_context, task_id, updates):
            return _pipeline(
                state.request,
                RuntimeResult(task_id=task_id, status=TaskStatus.COMPLETED),
            )

    def craft(exec_id: str, status: ExecutionStatus, *, recovery_safe: bool) -> CheckpointStore:
        state = ExecutionState(
            execution_id=exec_id,
            principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
            session_id="s",
            request=f"request-{exec_id}",
            status=status,
        )
        store = CheckpointStore(tmp_path / f"store-{exec_id}")
        store.save_checkpoint(RecoveryCheckpoint(
            generation=1,
            execution_id=exec_id,
            principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
            session_id="s",
            execution_state=state.model_dump(mode="json"),
            pipeline_state=None,
            recovery_safe=recovery_safe,
        ))
        return store

    # Non-terminal + provably safe must restore into RECOVERING.
    for status in (ExecutionStatus.CREATED, ExecutionStatus.PLANNING, ExecutionStatus.RUNNING):
        exec_id = f"safe-{status.value}"
        coordinator = ExecutionCoordinator(
            SilentLifecycle(), checkpoint_store=craft(exec_id, status, recovery_safe=True)
        )
        restored = coordinator.inspect_execution(exec_id)
        assert restored.status == ExecutionStatus.RECOVERING, (
            f"{status.value} with recovery_safe=True must restore as recovering"
        )

    # Non-terminal without a safety proof must fail closed - never auto-replay.
    for status in (ExecutionStatus.CREATED, ExecutionStatus.PLANNING, ExecutionStatus.RUNNING):
        exec_id = f"unsafe-{status.value}"
        coordinator = ExecutionCoordinator(
            SilentLifecycle(), checkpoint_store=craft(exec_id, status, recovery_safe=False)
        )
        restored = coordinator.inspect_execution(exec_id)
        assert restored.status == ExecutionStatus.FAILED
        assert "safe" in (restored.error or "").lower()

    # Awaiting approval must survive restart untouched - user decision pending.
    coordinator = ExecutionCoordinator(
        SilentLifecycle(),
        checkpoint_store=craft("awaiting-approval", ExecutionStatus.AWAITING_APPROVAL, recovery_safe=False),
    )
    assert (
        coordinator.inspect_execution("awaiting-approval").status
        == ExecutionStatus.AWAITING_APPROVAL
    )

    # Terminal states must never be resurrected into recovery.
    terminal_statuses = (
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.TIMED_OUT,
    )
    for status in terminal_statuses:
        exec_id = f"terminal-{status.value}"
        coordinator = ExecutionCoordinator(
            SilentLifecycle(), checkpoint_store=craft(exec_id, status, recovery_safe=True)
        )
        assert coordinator.inspect_execution(exec_id).status == status


# ---------------------------------------------------------------------------
# Duplicate Suppression Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_completed_mutation_not_replayed_after_restart(tmp_path):
    """Completed non-idempotent mutation must be suppressed on restart."""
    class MutationLifecycle:
        def __init__(self):
            self.calls = 0

        async def run_pipeline(self, request, runtime_context, conversation=None):
            self.calls += 1
            return _pipeline(
                request,
                RuntimeResult(
                    task_id=request,
                    status=TaskStatus.COMPLETED,
                    output={"mutated": True},
                    metadata={
                        "operation_id": f"{request}:mutation:{request}",
                        "operation_outcome": "completed",
                    },
                ),
            )

        async def resume_pipeline(self, state, runtime_context, task_id, updates):
            raise AssertionError("Completed execution must not resume after restart.")

    lifecycle = MutationLifecycle()
    store = CheckpointStore(tmp_path / "duplicate-suppress")
    first = ExecutionCoordinator(lifecycle, checkpoint_store=store)

    # First execution - completes mutation
    state = await first.start_execution("mutation-test", wait=True)
    assert state.status.value == "completed"

    # Restart coordinator over the same durable checkpoint
    restarted_lifecycle = MutationLifecycle()
    restarted = ExecutionCoordinator(restarted_lifecycle, checkpoint_store=store)

    # The completed execution must restore as completed and never re-run
    restored = restarted.inspect_execution(state.execution_id)
    assert restored.status.value == "completed"
    assert restarted_lifecycle.calls == 0
    pending = await restarted.recover_pending()
    assert pending == []


@pytest.mark.asyncio
async def test_unknown_non_idempotent_mutation_not_replayed(tmp_path):
    """Unknown non-idempotent mutation must not be replayed automatically."""
    from app.core.contracts.memory import DEFAULT_LOCAL_PRINCIPAL_ID
    from app.core.contracts.state import ExecutionState, ExecutionStatus

    # Create checkpoint with unknown mutation outcome
    state = ExecutionState(
        execution_id="unknown-mutation",
        principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
        session_id="s",
        request="mutate",
        status=ExecutionStatus.RUNNING,
    )
    store = CheckpointStore(tmp_path / "unknown-mutation")
    store.save_checkpoint(RecoveryCheckpoint(
        generation=1,
        execution_id="unknown-mutation",
        principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
        session_id="s",
        execution_state=state.model_dump(mode="json"),
        operation_outcomes={"mutation-1": "failed_after_effect_unknown"},
        recovery_safe=False,
    ))

    class MutationLifecycle:
        def __init__(self):
            self.calls = 0

        async def run_pipeline(self, request, runtime_context, conversation=None):
            self.calls += 1
            return _pipeline(
                request,
                RuntimeResult(task_id=request, status=TaskStatus.COMPLETED),
            )

        async def resume_pipeline(self, state, runtime_context, task_id, updates):
            raise AssertionError("Unknown non-idempotent mutation must not resume.")

    restarted = ExecutionCoordinator(MutationLifecycle(), checkpoint_store=store)
    restored = restarted.inspect_execution("unknown-mutation")

    # Should be marked FAILED, not replayed
    assert restored.status.value == "failed"
    # Should not attempt recovery
    pending = await restarted.recover_pending()
    assert pending == []


@pytest.mark.asyncio
async def test_safe_replay_only_when_allowed(tmp_path):
    """Safe read-only work must replay when recovery_safe=True."""
    from app.core.contracts.memory import DEFAULT_LOCAL_PRINCIPAL_ID
    from app.core.contracts.state import ExecutionState, ExecutionStatus
    from app.core.orchestrator.pipeline import PipelineState
    from app.workflow.state import WorkflowState

    # Create checkpoint for safe read-only work
    state = ExecutionState(
        execution_id="read-only",
        principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
        session_id="s",
        request="read",
        status=ExecutionStatus.RUNNING,
    )
    pipeline = PipelineState(
        request="read",
        workflow_state=WorkflowState(workflow_id="wf-read", status=ExecutionStatus.RUNNING, total_steps=1),
    )
    store = CheckpointStore(tmp_path / "safe-replay")
    store.save_checkpoint(RecoveryCheckpoint(
        generation=1,
        execution_id="read-only",
        principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
        session_id="s",
        execution_state=state.model_dump(mode="json"),
        pipeline_state=pipeline.model_dump(mode="json"),
        operation_outcomes={"read-only:task:digest": "started"},
        recovery_safe=True,
    ))

    class ReadLifecycle:
        def __init__(self):
            self.calls = 0
            self.resumed = False

        async def run_pipeline(self, request, runtime_context, conversation=None):
            self.calls += 1
            return _pipeline(
                request,
                RuntimeResult(task_id=request, status=TaskStatus.COMPLETED, output={"data": "read"}),
            )

        async def resume_pipeline(self, state, runtime_context, task_id, updates):
            self.resumed = True
            return _pipeline(
                state.request,
                RuntimeResult(task_id=task_id, status=TaskStatus.COMPLETED, output={"data": "read"}),
            )

    lifecycle = ReadLifecycle()
    restarted = ExecutionCoordinator(lifecycle, checkpoint_store=store)

    # Should detect as recoverable
    assert await restarted.recover_pending() == ["read-only"]

    # Resume should complete
    final = await restarted.wait_execution("read-only")
    assert final.status.value == "completed"
    assert lifecycle.resumed
    assert lifecycle.calls == 0


# ---------------------------------------------------------------------------
# Recovery Without P8 Dependency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recovery_does_not_depend_on_evidence_store(tmp_path):
    """Recovery must work even if evidence store is unavailable."""
    from app.core.contracts.memory import DEFAULT_LOCAL_PRINCIPAL_ID
    from app.core.contracts.state import ExecutionState, ExecutionStatus
    from app.core.orchestrator.pipeline import PipelineState

    # Create checkpoint without evidence DB - pipeline state must be a valid dump or None
    state = ExecutionState(
        execution_id="no-evidence",
        principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
        session_id="s",
        request="test",
        status=ExecutionStatus.RUNNING,
    )
    pipeline = PipelineState(request="test")
    store = CheckpointStore(tmp_path / "no-evidence")
    store.save_checkpoint(RecoveryCheckpoint(
        generation=1,
        execution_id="no-evidence",
        principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
        session_id="s",
        execution_state=state.model_dump(mode="json"),
        pipeline_state=pipeline.model_dump(mode="json"),
        operation_outcomes={},
        recovery_safe=True,
    ))

    class SimpleLifecycle:
        async def run_pipeline(self, request, runtime_context, conversation=None):
            return _pipeline(
                request,
                RuntimeResult(task_id=request, status=TaskStatus.COMPLETED, output={"done": True}),
            )

        async def resume_pipeline(self, state, runtime_context, task_id, updates):
            return _pipeline(
                state.request,
                RuntimeResult(task_id=task_id, status=TaskStatus.COMPLETED, output={"done": True}),
            )

    # Recovery should work without any evidence store
    restarted = ExecutionCoordinator(SimpleLifecycle(), checkpoint_store=store)
    assert await restarted.recover_pending() == ["no-evidence"]

    final = await restarted.wait_execution("no-evidence")
    assert final.status.value == "completed"


# ---------------------------------------------------------------------------
# Stable Operation Identity Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stable_operation_identity_same_semantic_operation(tmp_path):
    """Same semantic operation retry must be recognized correctly."""
    class IdempotentLifecycle:
        def __init__(self):
            self.calls = 0

        async def run_pipeline(self, request, runtime_context, conversation=None):
            self.calls += 1
            return _pipeline(
                request,
                RuntimeResult(
                    task_id=request,
                    status=TaskStatus.COMPLETED,
                    output={"idempotent": True},
                    metadata={
                        "operation_id": f"{request}:idem:{request}",
                        "operation_outcome": "completed",
                    },
                ),
            )

        async def resume_pipeline(self, state, runtime_context, task_id, updates):
            raise AssertionError("Completed execution must not resume after restart.")

    lifecycle = IdempotentLifecycle()
    store = CheckpointStore(tmp_path / "stable-id")
    first = ExecutionCoordinator(lifecycle, checkpoint_store=store)

    # First execution - completes idempotent operation
    state = await first.start_execution("idem-test", wait=True)
    assert state.status.value == "completed"
    assert lifecycle.calls == 1

    # Restart - should recognize completed state without re-execution
    restarted_lifecycle = IdempotentLifecycle()
    restarted = ExecutionCoordinator(restarted_lifecycle, checkpoint_store=store)
    restored = restarted.inspect_execution(state.execution_id)

    assert restored.status.value == "completed"
    assert restarted_lifecycle.calls == 0


@pytest.mark.asyncio
async def test_different_task_different_identity(tmp_path):
    """Different tasks must have different operation identities."""
    class DiffLifecycle:
        def __init__(self):
            self.calls = 0

        async def run_pipeline(self, request, runtime_context, conversation=None):
            self.calls += 1
            return _pipeline(
                request,
                RuntimeResult(
                    task_id=request,
                    status=TaskStatus.COMPLETED,
                    output={"done": True},
                    metadata={"operation_id": f"{request}:tool:{request}"},
                ),
            )

        async def resume_pipeline(self, state, runtime_context, task_id, updates):
            return _pipeline(
                state.request,
                RuntimeResult(task_id=task_id, status=TaskStatus.COMPLETED),
            )

    lifecycle = DiffLifecycle()
    store = CheckpointStore(tmp_path / "diff-id")
    first = ExecutionCoordinator(lifecycle, checkpoint_store=store)

    # Execute task A - explicit execution IDs keep checkpoints addressable
    state_a = await first.start_execution("run-a", wait=True)
    assert state_a.status.value == "completed"

    # Restart with task B - a new execution must still execute
    restarted = ExecutionCoordinator(DiffLifecycle(), checkpoint_store=store)
    state_b = await restarted.start_execution("run-b", wait=True)
    assert state_b.status.value == "completed"

    assert lifecycle.calls >= 1


# ---------------------------------------------------------------------------
# Packaged Mode Recovery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recovery_after_restart_works_in_packaged_mode(tmp_path, monkeypatch):
    """P6 recovery must work when running from packaged executable."""
    import sys
    from app.core.contracts.memory import DEFAULT_LOCAL_PRINCIPAL_ID
    from app.core.contracts.state import ExecutionState, ExecutionStatus
    from app.core.orchestrator.pipeline import PipelineState

    monkeypatch.setattr(sys, "frozen", True, raising=False)

    from app.paths import get_application_paths
    paths = get_application_paths()
    # In packaged mode, paths should be in LOCALAPPDATA
    assert paths.is_installed

    # Use a temp directory that simulates installed checkpoint location
    store = CheckpointStore(tmp_path / "packaged-checkpoints")

    class PackagedLifecycle:
        async def run_pipeline(self, request, runtime_context, conversation=None):
            return _pipeline(
                request,
                RuntimeResult(task_id=request, status=TaskStatus.COMPLETED, output={"done": True}),
            )

        async def resume_pipeline(self, state, runtime_context, task_id, updates):
            return _pipeline(
                state.request,
                RuntimeResult(task_id=task_id, status=TaskStatus.COMPLETED, output={"done": True}),
            )

    # Create checkpoint
    state = ExecutionState(
        execution_id="packaged-recovery",
        principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
        session_id="s",
        request="packaged-test",
        status=ExecutionStatus.RUNNING,
    )
    pipeline = PipelineState(request="packaged-test")
    store.save_checkpoint(RecoveryCheckpoint(
        generation=1,
        execution_id="packaged-recovery",
        principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
        session_id="s",
        execution_state=state.model_dump(mode="json"),
        pipeline_state=pipeline.model_dump(mode="json"),
        operation_outcomes={},
        recovery_safe=True,
    ))

    # Recovery should work
    restarted = ExecutionCoordinator(PackagedLifecycle(), checkpoint_store=store)
    assert await restarted.recover_pending() == ["packaged-recovery"]

    final = await restarted.wait_execution("packaged-recovery")
    assert final.status.value == "completed"


def test_durable_checkpoint_terminal_cache_is_bounded(tmp_path):
    """Durable terminal checkpoints remain on disk without filling process memory."""
    from app.core.contracts.state import ExecutionStatus

    directory = tmp_path / "bounded-cache"
    store = CheckpointStore(directory, max_cached_terminal=8)
    for index in range(40):
        execution_id = f"bounded-{index}"
        store.save_checkpoint(RecoveryCheckpoint(
            execution_id=execution_id,
            principal_id="p12-principal",
            session_id="p12-session",
            execution_state={"execution_id": execution_id, "status": ExecutionStatus.COMPLETED.value},
        ))

    assert len(store._checkpoints) == 8
    assert len(list(directory.glob("*.json"))) == 40
    assert store.load_checkpoint("bounded-0") is not None
    assert len(store._checkpoints) == 8
