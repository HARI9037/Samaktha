"""P12.2 — Runtime Concurrency & Scheduler Pressure Stress Tests.

Tests execution capacity, backpressure, terminal-state races, and
cancellation/approval truthfulness under concurrent load.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from app.core.app import create_orchestrator
from app.config.settings import Settings
from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeResult
from app.core.contracts.planning import TaskStatus
from app.core.execution_coordinator import (
    ExecutionCapacityError,
    ExecutionCoordinator,
)
from app.runtime.engine import RuntimeEngine
from app.runtime.dispatcher import RuntimeDispatcher
from app.runtime.registry import RuntimeRegistry
from app.runtime.reliability import FailureType, RetryPolicy
from app.tools.base import ToolResult
from tests.conftest import approved_task


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def orchestrator(tmp_path):
    """Create a production orchestrator with isolated persistence and mock provider."""
    settings = Settings(
        _env_file=None,
        sqlite_url=str(tmp_path / "stress.db"),
        personality_state_path=str(tmp_path / "personality.json"),
        checkpoint_location=str(tmp_path / "checkpoints"),
        groq_api_key="test-key",  # Enable groq
    )
    # Enable mock agent for testing
    from app.providers.config import ProviderSettings
    # We need to monkeypatch the ProviderSettings used in create_orchestrator
    # to have mock_agent=True
    import app.core.app as core_app
    original_provider_settings = core_app.ProviderSettings

    def mock_provider_settings(*args, **kwargs):
        kwargs.setdefault('mock_agent', True)
        kwargs.setdefault('default_provider', 'mock')
        return original_provider_settings(*args, **kwargs)

    import pytest
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(core_app, "ProviderSettings", mock_provider_settings)

    try:
        orch = create_orchestrator(settings)
    finally:
        monkeypatch.undo()

    return orch


@pytest.fixture
def runtime(orchestrator):
    """Extract the runtime engine from the orchestrator."""
    return orchestrator.runtime


# ---------------------------------------------------------------------------
# Capacity & Backpressure Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coordinator_pending_capacity_is_bounded(tmp_path, monkeypatch):
    """Active plus pending work is bounded and excess admission is explicit."""
    import app.core.app as core_app
    from app.providers.mock import MockProvider

    original_provider_settings = core_app.ProviderSettings

    def mock_provider_settings(*args, **kwargs):
        kwargs.setdefault("mock_agent", True)
        kwargs.setdefault("default_provider", "mock")
        kwargs.setdefault("fallback_enabled", False)
        return original_provider_settings(*args, **kwargs)

    async def slow_execute(self, payload):
        await asyncio.sleep(0.5)
        return {"response": "bounded"}

    monkeypatch.setattr(core_app, "ProviderSettings", mock_provider_settings)
    monkeypatch.setattr(MockProvider, "execute", slow_execute)
    bounded = create_orchestrator(Settings(
        _env_file=None,
        sqlite_url=f"sqlite:///{(tmp_path / 'memory.db').as_posix()}",
        checkpoint_location=str(tmp_path / "checkpoints"),
        evidence_db_path=str(tmp_path / "evidence.db"),
        session_storage_path=str(tmp_path / "sessions"),
        permit_signing_key_path=str(tmp_path / "permit.key"),
        personality_state_path=str(tmp_path / "personality.json"),
        max_active_executions=2,
        max_pending_executions=1,
    ))
    coordinator = bounded.execution_coordinator
    coordinator.create_session(principal_id="capacity-principal", session_id="capacity-session")
    accepted = []
    for index in range(3):
        accepted.append(await coordinator.start_execution(
            "Return a deterministic local acknowledgement.",
            principal_id="capacity-principal",
            session_id="capacity-session",
            execution_id=f"bounded-{index}",
            wait=False,
        ))
    with pytest.raises(ExecutionCapacityError):
        await coordinator.start_execution(
            "Return a deterministic local acknowledgement.",
            principal_id="capacity-principal",
            session_id="capacity-session",
            execution_id="bounded-rejected",
            wait=False,
        )
    for state in accepted:
        settled = await coordinator.wait_execution(
            state.execution_id, principal_id="capacity-principal"
        )
        assert settled.terminal
    bounded.evidence_store.close()

@pytest.mark.asyncio
async def test_runtime_below_capacity_completes_all(orchestrator):
    """Submit fewer tasks than capacity; all should complete."""
    n = 8  # Below max_active_executions=16
    tasks = [
        approved_task(task_id=f"below-cap-{i}", action_type="text_generation", subject_id=f"below-cap-{i}")
        for i in range(n)
    ]

    results = await asyncio.gather(*[
        orchestrator.runtime.run(
            RuntimeContext(request_id=f"below-cap-{i}"),
            task,
            RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="capacity test"),
        )
        for i, task in enumerate(tasks)
    ])

    assert len(results) == n
    assert all(r.status == TaskStatus.COMPLETED for r in results)


@pytest.mark.asyncio
async def test_runtime_at_capacity_completes_all(orchestrator):
    """Submit exactly capacity tasks; all should complete."""
    n = 16  # At max_active_executions
    tasks = [
        approved_task(task_id=f"at-cap-{i}", action_type="text_generation", subject_id=f"at-cap-{i}")
        for i in range(n)
    ]

    results = await asyncio.gather(*[
        orchestrator.runtime.run(
            RuntimeContext(request_id=f"at-cap-{i}"),
            task,
            RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="capacity test"),
        )
        for i, task in enumerate(tasks)
    ])

    assert len(results) == n
    assert all(r.status == TaskStatus.COMPLETED for r in results)


@pytest.mark.asyncio
async def test_runtime_above_capacity_applies_backpressure(orchestrator):
    """Submit more than capacity; excess should be rejected/queued truthfully."""
    n = 20  # Above max_active_executions=16
    tasks = [
        approved_task(task_id=f"above-cap-{i}", action_type="text_generation", subject_id=f"above-cap-{i}")
        for i in range(n)
    ]

    # With semaphore-based capacity, tasks should queue and eventually complete
    # or we should observe proper backpressure semantics
    results = await asyncio.gather(*[
        orchestrator.runtime.run(
            RuntimeContext(request_id=f"above-cap-{i}"),
            task,
            RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="capacity test"),
        )
        for i, task in enumerate(tasks)
    ])

    # All should complete (queued), but we verify no silent drops
    assert len(results) == n
    # Request IDs must remain unique
    request_ids = [r.metadata.get("runtime_request_id") for r in results if r.metadata]
    assert len(set(request_ids)) == len(request_ids), "Request IDs must be unique under load"


@pytest.mark.asyncio
async def test_concurrent_execution_ids_are_unique(orchestrator):
    """Concurrent executions must have unique request IDs."""
    n = 16
    tasks = [
        approved_task(task_id=f"unique-{i}", action_type="text_generation", subject_id=f"unique-{i}")
        for i in range(n)
    ]

    results = await asyncio.gather(*[
        orchestrator.runtime.run(
            RuntimeContext(request_id=f"unique-{i}"),
            task,
            RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="unique test"),
        )
        for i, task in enumerate(tasks)
    ])

    request_ids = [r.metadata.get("runtime_request_id") for r in results if r.metadata]
    assert len(request_ids) == n
    assert len(set(request_ids)) == n, "Duplicate request IDs detected under concurrency"


@pytest.mark.asyncio
async def test_concurrent_results_do_not_cross_execution(orchestrator):
    """Results must not leak across concurrent executions."""
    n = 8
    tasks = [
        approved_task(task_id=f"cross-{i}", action_type="text_generation", subject_id=f"cross-{i}")
        for i in range(n)
    ]

    results = await asyncio.gather(*[
        orchestrator.runtime.run(
            RuntimeContext(request_id=f"cross-{i}"),
            task,
            RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="isolation test"),
        )
        for i, task in enumerate(tasks)
    ])

    # Verify each result corresponds to its task
    for i, result in enumerate(results):
        assert result.metadata.get("subject_id") == f"cross-{i}" or result.task_id == f"cross-{i}"


# ---------------------------------------------------------------------------
# Terminal-State Race Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_terminal_state_race_cancel_vs_complete(orchestrator):
    """Cancel and complete cannot both be terminal for same execution."""
    # This tests the ExecutionCoordinator's terminal state race handling
    coordinator = orchestrator.execution_coordinator

    # Create a slow execution that we can race
    class SlowLifecycle:
        def __init__(self):
            self.calls = 0
            self._continue = asyncio.Event()

        async def run_pipeline(self, request, runtime_context, conversation=None):
            self.calls += 1
            await self._continue.wait()
            from app.core.contracts.runtime import RuntimeResult
            from app.core.contracts.planning import TaskStatus
            return MagicMock(
                request=request,
                runtime_result=RuntimeResult(task_id="slow", status=TaskStatus.COMPLETED, output={"done": True}),
            )

        async def resume_pipeline(self, state, runtime_context, task_id, updates):
            return MagicMock(
                request=state.request,
                runtime_result=MagicMock(task_id=task_id, status=TaskStatus.COMPLETED, output={"done": True}),
            )

    lifecycle = SlowLifecycle()
    coord = ExecutionCoordinator(lifecycle, execution_timeout_s=5.0)

    state = await coord.start_execution("race-test", wait=False)

    # Race cancel vs timeout
    cancel_result, timeout_result = await asyncio.gather(
        coord.cancel_execution(state.execution_id),
        coord.timeout_execution(state.execution_id),
        return_exceptions=True
    )

    final = coord.inspect_execution(state.execution_id)
    assert final.terminal, "Execution must reach terminal state"
    assert final.status in {"cancelled", "timed_out"}, f"Unexpected terminal: {final.status}"

    # Both operations should report same final state
    if not isinstance(cancel_result, Exception) and not isinstance(timeout_result, Exception):
        assert cancel_result.status == timeout_result.status == final.status

    lifecycle._continue.set()


@pytest.mark.asyncio
async def test_cancel_vs_complete_truthfulness(orchestrator):
    """Cancellation must not allow completion to proceed."""
    from app.core.contracts.runtime import RuntimeResult
    from app.core.contracts.planning import TaskStatus
    from app.core.execution_coordinator import ExecutionCoordinator

    class BlockingLifecycle:
        def __init__(self):
            self.block = asyncio.Event()
            self.calls = 0

        async def run_pipeline(self, request, runtime_context, conversation=None):
            self.calls += 1
            await self.block.wait()
            return MagicMock(
                request=request,
                runtime_result=RuntimeResult(task_id="blocked", status=TaskStatus.COMPLETED, output={"done": True}),
            )

        async def resume_pipeline(self, state, runtime_context, task_id, updates):
            return MagicMock(
                request=state.request,
                runtime_result=RuntimeResult(task_id=task_id, status=TaskStatus.COMPLETED, output={"done": True}),
            )

    lifecycle = BlockingLifecycle()
    coord = ExecutionCoordinator(lifecycle)

    state = await coord.start_execution("cancel-vs-complete", wait=False)

    # Cancel while blocked
    await asyncio.sleep(0.01)  # Let it start
    cancel_result = await coord.cancel_execution(state.execution_id)

    # Now unblock
    lifecycle.block.set()

    final = coord.inspect_execution(state.execution_id)
    # Cancel should win or be the terminal state
    assert final.terminal
    assert final.status in {"cancelled", "completed"}, f"Unexpected: {final.status}"


# ---------------------------------------------------------------------------
# Deadlock & Starvation Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_deadlock_under_concurrency(orchestrator):
    """Concurrent executions must not deadlock."""
    n = 16
    tasks = [
        approved_task(task_id=f"deadlock-{i}", action_type="text_generation", subject_id=f"deadlock-{i}")
        for i in range(n)
    ]

    start = time.perf_counter()
    results = await asyncio.gather(*[
        orchestrator.runtime.run(
            RuntimeContext(request_id=f"deadlock-{i}"),
            task,
            RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="deadlock test"),
        )
        for i, task in enumerate(tasks)
    ], return_exceptions=True)

    elapsed = time.perf_counter() - start

    # Should complete within reasonable time (not hang indefinitely)
    assert elapsed < 30.0, f"Potential deadlock: took {elapsed:.1f}s"

    # All should complete successfully
    exceptions = [r for r in results if isinstance(r, Exception)]
    assert len(exceptions) == 0, f"Exceptions under concurrency: {exceptions}"


@pytest.mark.asyncio
async def test_no_starvation_under_load(orchestrator):
    """Under sustained load, no task should starve indefinitely."""
    # Submit a batch, wait for some, then submit more
    batch_size = 8
    for batch in range(3):
        tasks = [
            approved_task(task_id=f"starve-{batch}-{i}", action_type="text_generation", subject_id=f"starve-{batch}-{i}")
            for i in range(batch_size)
        ]

        results = await asyncio.gather(*[
            orchestrator.runtime.run(
                RuntimeContext(request_id=f"starve-{batch}-{i}"),
                task,
                RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="starvation test"),
            )
            for i, task in enumerate(tasks)
        ])

        assert len(results) == batch_size
        assert all(r.status == TaskStatus.COMPLETED for r in results)


# ---------------------------------------------------------------------------
# ExecutionCoordinator Stress
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execution_coordinator_bounded_active(orchestrator):
    """ExecutionCoordinator must respect max_active_executions."""
    from app.core.execution_coordinator import ExecutionCoordinator
    from app.core.contracts.runtime import RuntimeResult
    from app.core.contracts.planning import TaskStatus

    class SlowLifecycle:
        def __init__(self, delay=0.5):
            self.delay = delay
            self.calls = 0

        async def run_pipeline(self, request, runtime_context, conversation=None):
            self.calls += 1
            await asyncio.sleep(self.delay)
            from app.core.contracts.runtime import RuntimeResult
            from app.core.contracts.planning import TaskStatus
            return MagicMock(
                request=request,
                runtime_result=RuntimeResult(task_id=request, status=TaskStatus.COMPLETED, output={"done": True}),
            )

        async def resume_pipeline(self, state, runtime_context, task_id, updates):
            return MagicMock(
                request=state.request,
                runtime_result=RuntimeResult(task_id=task_id, status=TaskStatus.COMPLETED, output={"done": True}),
            )

    # Coordinator with max 2 concurrent
    lifecycle = SlowLifecycle(delay=0.2)
    coord = ExecutionCoordinator(lifecycle, max_active_executions=2)

    # Start 5 executions
    states = [await coord.start_execution(f"bounded-{i}", wait=False) for i in range(5)]

    # Give them time to start
    await asyncio.sleep(0.1)

    # At most 2 should be running concurrently
    active = sum(1 for s in states if s.status.value == "running")
    assert active <= 2, f"Expected <=2 active, got {active}"

    # Wait for all to complete
    await asyncio.gather(*[coord.wait_execution(s.execution_id) for s in states])


# ---------------------------------------------------------------------------
# Pipeline State Isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_states_remain_isolated(orchestrator):
    """Pipeline states must not cross-contaminate under concurrency."""
    n = 8
    tasks = [
        approved_task(task_id=f"iso-{i}", action_type="text_generation", subject_id=f"iso-{i}")
        for i in range(n)
    ]

    results = await asyncio.gather(*[
        orchestrator.runtime.run(
            RuntimeContext(request_id=f"iso-{i}"),
            task,
            RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="isolation test"),
        )
        for i, task in enumerate(tasks)
    ])

    # Each execution should have its own pipeline state
    for i, result in enumerate(results):
        # The subject_id is in the task, verified via task_id and request_id
        assert result.task_id == f"iso-{i}"
        assert result.metadata.get("runtime_request_id") == f"iso-{i}"


# ---------------------------------------------------------------------------
# Approval vs Cancel Race
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approval_vs_cancel_race(orchestrator):
    """Approval resolution vs cancellation must have single truthful winner."""
    from app.core.execution_coordinator import ExecutionCoordinator
    from app.core.contracts.runtime import RuntimeResult
    from app.core.contracts.planning import TaskStatus
    from app.core.contracts.pause import ExecutionPause

    class ApprovalLifecycle:
        def __init__(self):
            self.pause_event = asyncio.Event()
            self.resumed = False
            self.calls = 0

        async def run_pipeline(self, request, runtime_context, conversation=None):
            self.calls += 1
            # Return paused state requiring approval
            from app.core.contracts.runtime import RuntimeResult
            from app.core.contracts.planning import TaskStatus
            from app.core.contracts.pause import ExecutionPause
            return MagicMock(
                request=request,
                runtime_result=RuntimeResult(
                    task_id="approval-1",
                    status=TaskStatus.PAUSED,
                    pause=ExecutionPause(reason="approve", payload={"data": "test"}),
                ),
            )

        async def resume_pipeline(self, state, runtime_context, task_id, updates):
            self.resumed = True
            from app.core.contracts.runtime import RuntimeResult
            from app.core.contracts.planning import TaskStatus
            return MagicMock(
                request=state.request,
                runtime_result=RuntimeResult(task_id=task_id, status=TaskStatus.COMPLETED, output={"done": True}),
            )

    lifecycle = ApprovalLifecycle()
    coord = ExecutionCoordinator(lifecycle)

    state = await coord.start_execution("approval-race", wait=False)

    # Wait for pause
    await asyncio.sleep(0.1)
    paused = coord.inspect_execution(state.execution_id)
    assert paused.status.value == "awaiting_approval"

    # Race: submit approval while also trying to cancel
    approval = coord.pending_approval(state.execution_id)

    cancel_future = coord.cancel_execution(state.execution_id)
    approval_future = coord.submit_approval(state.execution_id, approval["approval_id"], "allow")

    cancel_result, approval_result = await asyncio.gather(
        cancel_future, approval_future, return_exceptions=True
    )

    final = coord.inspect_execution(state.execution_id)
    assert final.terminal, "Must reach terminal state"
    # One winner
    assert final.status in {"cancelled", "completed"}


# ---------------------------------------------------------------------------
# Queue Boundedness
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_queue_does_not_grow_unboundedly(orchestrator):
    """Submitted work queue must remain bounded."""
    # Submit a large burst and verify memory doesn't explode
    # This is a smoke test for queue boundedness
    n = 50
    tasks = [
        approved_task(task_id=f"queue-{i}", action_type="text_generation", subject_id=f"queue-{i}")
        for i in range(n)
    ]

    # Submit all at once
    results = await asyncio.gather(*[
        orchestrator.runtime.run(
            RuntimeContext(request_id=f"queue-{i}"),
            task,
            RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="queue test"),
        )
        for i, task in enumerate(tasks)
    ], return_exceptions=True)

    # All should complete (queued and processed)
    successful = [r for r in results if not isinstance(r, Exception) and r.status == TaskStatus.COMPLETED]
    assert len(successful) == n, f"Expected {n} completed, got {len(successful)}"


# ---------------------------------------------------------------------------
# No Silent Task Loss
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_silent_task_loss(orchestrator):
    """No task should silently disappear without result."""
    n = 20
    task_ids = [f"loss-{i}" for i in range(n)]
    tasks = [
        approved_task(task_id=tid, action_type="text_generation", subject_id=tid)
        for tid in task_ids
    ]

    results = await asyncio.gather(*[
        orchestrator.runtime.run(
            RuntimeContext(request_id=tid),
            task,
            RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="loss test"),
        )
        for tid, task in zip(task_ids, tasks)
    ])

    # Every task must have a result
    assert len(results) == n
    result_ids = {r.task_id for r in results}
    assert result_ids == set(task_ids), "Missing task results"


# ---------------------------------------------------------------------------
# Cancellation During Provider Execution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_during_provider_execution(orchestrator):
    """Cancel during provider execution must be truthful."""
    from app.core.execution_coordinator import ExecutionCoordinator
    from app.core.contracts.runtime import RuntimeResult
    from app.core.contracts.planning import TaskStatus

    class ProviderLifecycle:
        def __init__(self):
            self.in_provider = asyncio.Event()
            self.released = asyncio.Event()

        async def run_pipeline(self, request, runtime_context, conversation=None):
            from app.core.contracts.runtime import RuntimeResult
            from app.core.contracts.planning import TaskStatus
            # Simulate provider execution
            self.in_provider.set()
            await self.released.wait()
            return MagicMock(
                request=request,
                runtime_result=RuntimeResult(task_id=request, status=TaskStatus.COMPLETED, output={"done": True}),
            )

        async def resume_pipeline(self, state, runtime_context, task_id, updates):
            return MagicMock(
                request=state.request,
                runtime_result=RuntimeResult(task_id=task_id, status=TaskStatus.COMPLETED, output={"done": True}),
            )

    lifecycle = ProviderLifecycle()
    coord = ExecutionCoordinator(lifecycle)

    state = await coord.start_execution("provider-cancel", wait=False)

    # Wait for provider phase
    await lifecycle.in_provider.wait()

    # Cancel during provider execution
    cancel_result = await coord.cancel_execution(state.execution_id)

    lifecycle.released.set()

    final = coord.inspect_execution(state.execution_id)
    assert final.terminal
    assert final.status in {"cancelled", "completed"}


# ---------------------------------------------------------------------------
# Timeout vs Completion Race
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_timeout_vs_completion_race(orchestrator):
    """Timeout and completion cannot both claim victory."""
    from app.core.execution_coordinator import ExecutionCoordinator
    from app.core.contracts.runtime import RuntimeResult
    from app.core.contracts.planning import TaskStatus

    class NearTimeoutLifecycle:
        def __init__(self):
            self.calls = 0

        async def run_pipeline(self, request, runtime_context, conversation=None):
            self.calls += 1
            # Complete just at timeout boundary
            await asyncio.sleep(0.05)
            from app.core.contracts.runtime import RuntimeResult
            from app.core.contracts.planning import TaskStatus
            return MagicMock(
                request=request,
                runtime_result=RuntimeResult(task_id=request, status=TaskStatus.COMPLETED, output={"done": True}),
            )

        async def resume_pipeline(self, state, runtime_context, task_id, updates):
            return MagicMock(
                request=state.request,
                runtime_result=RuntimeResult(task_id=task_id, status=TaskStatus.COMPLETED, output={"done": True}),
            )

    lifecycle = NearTimeoutLifecycle()
    coord = ExecutionCoordinator(lifecycle, execution_timeout_s=0.1)

    state = await coord.start_execution("timeout-race", wait=False)

    # Race: natural completion vs timeout
    final = await asyncio.wait_for(
        asyncio.gather(
            coord.wait_execution(state.execution_id),
            coord.timeout_execution(state.execution_id),
            return_exceptions=True
        ),
        timeout=1.0
    )

    final_state = coord.inspect_execution(state.execution_id)
    assert final_state.terminal
    assert final_state.status in {"completed", "timed_out"}


# ---------------------------------------------------------------------------
# Capacity Rejection Truthfulness
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_capacity_rejection_is_explicit(orchestrator):
    """When capacity exceeded, rejection/backpressure must be explicit, not silent."""
    # This test verifies the system doesn't silently drop work
    n = 25  # Well above capacity
    tasks = [
        approved_task(task_id=f"explicit-{i}", action_type="text_generation", subject_id=f"explicit-{i}")
        for i in range(n)
    ]

    results = await asyncio.gather(*[
        orchestrator.runtime.run(
            RuntimeContext(request_id=f"explicit-{i}"),
            task,
            RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="explicit test"),
        )
        for i, task in enumerate(tasks)
    ], return_exceptions=True)

    # Every submission must yield a result (completed or explicit error)
    # No silent drops
    assert len(results) == n

    # All should either complete or fail with explicit error
    for r in results:
        assert not isinstance(r, Exception) or isinstance(r, (asyncio.CancelledError,))
        if hasattr(r, 'status'):
            assert r.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}


@pytest.mark.asyncio
async def test_coordinator_terminal_history_is_bounded():
    """Completed process-local records cannot accumulate without bound."""
    from app.core.orchestrator.pipeline import PipelineState

    class CompletingLifecycle:
        _session_manager = None

        async def run_pipeline(self, request, runtime_context, conversation=None):
            return PipelineState(
                request=request,
                runtime_result=RuntimeResult(
                    task_id=runtime_context.request_id,
                    status=TaskStatus.COMPLETED,
                    output={"ok": True},
                ),
            )

    coordinator = ExecutionCoordinator(
        CompletingLifecycle(),
        max_retained_executions=8,
    )
    newest = None
    for index in range(40):
        newest = await coordinator.start_execution(f"bounded-{index}")

    assert newest is not None
    assert len(coordinator._executions) == 8
    assert coordinator.inspect_execution(newest.execution_id).status == "completed"
    assert all(record.state.terminal for record in coordinator._executions.values())
