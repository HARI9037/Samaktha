from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import app.core.app as core_app
from app.config.settings import Settings
from app.core.app import create_orchestrator
from app.core.contracts import RoutingDecision, RuntimeContext
from app.core.contracts.pause import ExecutionPause
from app.core.contracts.planning import TaskStatus
from app.core.contracts.runtime import RuntimeResult
from app.core.contracts.state import ExecutionState, ExecutionStatus
from app.core.execution_coordinator import ExecutionAccessError, ExecutionCoordinator
from app.core.orchestrator.pipeline import PipelineState
from app.workflow.state import WorkflowState
from app.providers.base import BaseProvider
from app.providers.config import ProviderSettings
from app.tools.base import ToolResult
from app.runtime.checkpoint import (
    CheckpointInvalidError,
    CheckpointStore,
    CheckpointStaleError,
    CheckpointVersionError,
    RecoveryCheckpoint,
)
from app.runtime.dispatcher import RuntimeDispatcher
from app.runtime.engine import RuntimeEngine
from app.runtime.registry import RuntimeRegistry
from app.runtime.reliability import (
    FailureType,
    OperationOutcome,
    RetryPolicy,
    SideEffectClass,
    classify_failure,
)
from tests.conftest import approved_task


def test_failure_classification_and_retryability_are_explicit():
    policy = RetryPolicy(max_attempts=2)
    assert classify_failure("429 rate limited") == FailureType.RATE_LIMITED
    assert classify_failure("provider timeout") == FailureType.PROVIDER_TIMEOUT
    assert classify_failure("invalid request") == FailureType.INVALID_REQUEST
    assert classify_failure("permit expired") == FailureType.PERMIT_EXPIRED
    assert policy.allows(
        FailureType.CONNECTION_ERROR,
        attempt=1,
        side_effect=SideEffectClass.READ_ONLY,
        outcome=OperationOutcome.FAILED_BEFORE_EFFECT,
    )
    for failure in (
        FailureType.INVALID_REQUEST,
        FailureType.CANCELLED,
        FailureType.AUTHORIZATION_DENIED,
        FailureType.PERMIT_INVALID,
        FailureType.MODEL_UNAVAILABLE,
    ):
        assert not policy.allows(
            failure,
            attempt=1,
            side_effect=SideEffectClass.READ_ONLY,
            outcome=OperationOutcome.FAILED_BEFORE_EFFECT,
        )


class _SequenceExecutor:
    def __init__(self, failures: list[str]):
        self.failures = list(failures)
        self.calls = 0

    async def execute(self, context, task, routing):
        self.calls += 1
        if self.failures:
            error = self.failures.pop(0)
            return RuntimeResult(task_id=task.task_id, status=TaskStatus.FAILED, error=error)
        return RuntimeResult(task_id=task.task_id, status=TaskStatus.COMPLETED, output={"ok": True})


def _runtime(executor, *, attempts=3, sleeper=None):
    registry = RuntimeRegistry()
    registry.register("provider", executor)
    registry.register("tool", executor)
    return RuntimeEngine(
        RuntimeDispatcher(registry),
        retry_policy=RetryPolicy(max_attempts=attempts, initial_delay_s=0.01, max_delay_s=0.02),
        sleeper=sleeper,
    )


@pytest.mark.asyncio
async def test_transient_provider_retry_is_bounded_and_evidenced():
    delays = []

    async def sleep(delay):
        delays.append(delay)

    executor = _SequenceExecutor(["connection reset", "503 server error", "still unavailable"])
    result = await _runtime(executor, attempts=3, sleeper=sleep).run(
        RuntimeContext(request_id="retry-1"),
        approved_task(task_id="provider-1", action_type="text_generation", subject_id="retry-1"),
        RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="test"),
    )
    assert result.status == TaskStatus.FAILED
    assert executor.calls == 3
    assert result.metadata["retry_count"] == 2
    assert delays == [0.01, 0.02]


@pytest.mark.asyncio
async def test_nonretryable_and_cancelled_failures_execute_once():
    for error, metadata in (
        ("invalid request", {}),
        ("authorization denied", {}),
        ("connection reset", {"cancel_requested": True}),
    ):
        executor = _SequenceExecutor([error])
        result = await _runtime(executor).run(
            RuntimeContext(request_id=f"once-{error}", metadata=metadata),
            approved_task(task_id="provider-once", action_type="text_generation", subject_id=f"once-{error}"),
            RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="test"),
        )
        assert result.status == TaskStatus.FAILED
        assert executor.calls == 1


@pytest.mark.asyncio
async def test_mutating_tool_unknown_outcome_is_not_auto_retried():
    executor = _SequenceExecutor(["tool timed out after dispatch"])
    result = await _runtime(executor).run(
        RuntimeContext(request_id="mutation-1"),
        approved_task(
            task_id="tool-1", action_type="tool",
            subject_id="mutation-1",
            metadata={"tool": "filesystem", "side_effect_class": "non_idempotent_mutation"},
        ),
        RoutingDecision(provider_id="local", model_id="none", reasoning_summary="tool"),
    )
    assert executor.calls == 1
    assert result.metadata["operation_outcome"] == "timed_out_unknown"
    assert result.metadata["operation_id"].startswith("mutation-1:tool-1:")


@pytest.mark.asyncio
async def test_recovered_completed_side_effect_is_suppressed_before_dispatch():
    executor = _SequenceExecutor([])
    task = approved_task(
        task_id="tool-completed", action_type="tool", subject_id="recovered-effect",
        metadata={"tool": "filesystem", "side_effect_class": "non_idempotent_mutation"},
    )
    operation_id = f"recovered-effect:{task.task_id}:{task.permit.operation_digest}"
    saved = RuntimeResult(
        task_id=task.task_id,
        status=TaskStatus.COMPLETED,
        output={"written": True},
        metadata={"operation_id": operation_id, "operation_outcome": "completed"},
    )
    result = await _runtime(executor).run(
        RuntimeContext(
            request_id="recovered-effect",
            metadata={"recovered_operation_results": {operation_id: saved.model_dump(mode="json")}},
        ),
        task,
        RoutingDecision(provider_id="local", model_id="none", reasoning_summary="tool"),
    )
    assert result.status == TaskStatus.COMPLETED
    assert result.output == {"written": True}
    assert result.metadata["duplicate_suppressed"] is True
    assert executor.calls == 0


class _Lifecycle:
    _session_manager = None

    def __init__(self, pause=False, block=False):
        self.pause = pause
        self.block = block
        self.calls = 0
        self.resumed = 0

    async def run_pipeline(self, request, runtime_context, conversation=None):
        self.calls += 1
        if self.block:
            await asyncio.Event().wait()
        return PipelineState(
            request=request,
            runtime_result=RuntimeResult(
                task_id="approval-1" if self.pause else "provider-1",
                status=TaskStatus.PAUSED if self.pause else TaskStatus.COMPLETED,
                pause=ExecutionPause(reason="approve") if self.pause else None,
                output={} if self.pause else {"content": "done"},
            ),
        )

    async def resume_pipeline(self, state, runtime_context, task_id, updates):
        self.resumed += 1
        return PipelineState(
            request=state.request,
            runtime_result=RuntimeResult(task_id=task_id, status=TaskStatus.COMPLETED, output={"content": "done"}),
        )


@pytest.mark.asyncio
async def test_execution_timeout_is_truthful_and_forms_no_completion():
    coordinator = ExecutionCoordinator(_Lifecycle(block=True), execution_timeout_s=0.01)
    state = await coordinator.start_execution("slow")
    result = coordinator.result(state.execution_id)
    assert state.status == ExecutionStatus.TIMED_OUT
    assert result.status == TaskStatus.FAILED
    assert result.metadata["execution_report"]["success"] is False


@pytest.mark.asyncio
async def test_cancel_timeout_completion_races_have_one_terminal_winner():
    coordinator = ExecutionCoordinator(_Lifecycle(block=True))
    running = await coordinator.start_execution("slow", wait=False)
    cancel, timeout = await asyncio.gather(
        coordinator.cancel_execution(running.execution_id),
        coordinator.timeout_execution(running.execution_id),
    )
    final = coordinator.inspect_execution(running.execution_id)
    assert final.terminal
    assert final.status in {ExecutionStatus.CANCELLED, ExecutionStatus.TIMED_OUT}
    assert cancel.status == timeout.status == final.status


@pytest.mark.asyncio
async def test_active_execution_concurrency_is_bounded():
    active = 0
    peak = 0
    release = asyncio.Event()

    class Limited(_Lifecycle):
        async def run_pipeline(self, request, runtime_context, conversation=None):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await release.wait()
            active -= 1
            return await super().run_pipeline(request, runtime_context, conversation)

    coordinator = ExecutionCoordinator(Limited(), max_active_executions=2)
    states = [await coordinator.start_execution(str(i), wait=False) for i in range(5)]
    await asyncio.sleep(0)
    assert peak == 2
    release.set()
    await asyncio.gather(*(coordinator.wait_execution(state.execution_id) for state in states))
    assert all(coordinator.inspect_execution(state.execution_id).status == ExecutionStatus.COMPLETED for state in states)


def test_checkpoint_contract_is_versioned_atomic_and_secret_safe(tmp_path: Path):
    store = CheckpointStore(tmp_path)
    checkpoint = RecoveryCheckpoint(
        execution_id="execution-1", principal_id="user-a", session_id="session-a",
        execution_state=ExecutionState(
            execution_id="execution-1", principal_id="user-a", session_id="session-a"
        ).model_dump(mode="json"),
    )
    store.save_checkpoint(checkpoint)
    loaded = store.load_checkpoint("execution-1")
    assert loaded.execution_id == "execution-1"
    assert not list(tmp_path.glob("*.tmp"))
    assert json.loads((tmp_path / "execution-1.json").read_text())["schema_version"] == 1
    secret = checkpoint.model_copy(update={"pipeline_state": {"openai_api_key": "secret"}})
    with pytest.raises(CheckpointInvalidError):
        store.save_checkpoint(secret)
    with pytest.raises(CheckpointStaleError):
        store.save_checkpoint(checkpoint)


def test_corrupt_and_incompatible_checkpoints_are_rejected_without_global_startup_failure(tmp_path: Path):
    (tmp_path / "corrupt.json").write_text("{not-json", encoding="utf-8")
    (tmp_path / "future.json").write_text(json.dumps({"schema_version": 999}), encoding="utf-8")
    store = CheckpointStore(tmp_path)
    with pytest.raises(CheckpointInvalidError):
        store.load_checkpoint("corrupt")
    with pytest.raises(CheckpointVersionError):
        store.load_checkpoint("future")
    assert store.list_checkpoints() == []
    ExecutionCoordinator(_Lifecycle(), checkpoint_store=store)


@pytest.mark.asyncio
async def test_awaiting_approval_survives_restart_with_same_identity(tmp_path: Path):
    store = CheckpointStore(tmp_path)
    orchestrator = _Lifecycle(pause=True)
    first = ExecutionCoordinator(orchestrator, checkpoint_store=store)
    waiting = await first.start_execution(
        "write", principal_id="user-a", session_id="session-a"
    )
    approval = first.pending_approval(waiting.execution_id, principal_id="user-a")

    restarted = ExecutionCoordinator(orchestrator, checkpoint_store=CheckpointStore(tmp_path))
    restored = restarted.inspect_execution(waiting.execution_id, principal_id="user-a")
    assert restored.status == ExecutionStatus.AWAITING_APPROVAL
    assert restored.execution_id == waiting.execution_id
    assert restarted.pending_approval(waiting.execution_id, principal_id="user-a")["approval_id"] == approval["approval_id"]
    with pytest.raises(ExecutionAccessError):
        restarted.inspect_execution(waiting.execution_id, principal_id="user-b")
    completed = await restarted.submit_approval(
        waiting.execution_id, approval["approval_id"], "allow", principal_id="user-a"
    )
    assert completed.status == ExecutionStatus.COMPLETED
    assert orchestrator.resumed == 1


@pytest.mark.asyncio
async def test_terminal_execution_is_restored_but_never_reexecuted(tmp_path: Path):
    orchestrator = _Lifecycle()
    first = ExecutionCoordinator(orchestrator, checkpoint_store=CheckpointStore(tmp_path))
    completed = await first.start_execution("done", execution_id="stable-execution")
    assert orchestrator.calls == 1
    restarted = ExecutionCoordinator(orchestrator, checkpoint_store=CheckpointStore(tmp_path))
    restored = restarted.inspect_execution(completed.execution_id)
    assert restored.status == ExecutionStatus.COMPLETED
    assert restarted.result(completed.execution_id).output["content"] == "done"
    assert await restarted.recover_pending() == []
    assert orchestrator.calls == 1


@pytest.mark.asyncio
async def test_unknown_running_side_effect_is_not_replayed_after_restart(tmp_path: Path):
    state = ExecutionState(
        execution_id="uncertain", principal_id="local-default", session_id="default",
        request="mutate", status=ExecutionStatus.RUNNING,
    )
    store = CheckpointStore(tmp_path)
    store.save_checkpoint(RecoveryCheckpoint(
        execution_id="uncertain", principal_id="local-default", session_id="default",
        execution_state=state.model_dump(mode="json"),
        operation_outcomes={"operation-1": "failed_after_effect_unknown"},
        recovery_safe=False,
    ))
    orchestrator = _Lifecycle()
    restarted = ExecutionCoordinator(orchestrator, checkpoint_store=CheckpointStore(tmp_path))
    restored = restarted.inspect_execution("uncertain")
    assert restored.status == ExecutionStatus.FAILED
    assert orchestrator.calls == 0
    assert await restarted.recover_pending() == []


@pytest.mark.asyncio
async def test_recoverable_running_read_only_work_resumes_same_execution(tmp_path: Path):
    state = ExecutionState(
        execution_id="read-only", principal_id="local-default", session_id="default",
        request="read", status=ExecutionStatus.RUNNING,
    )
    pipeline = PipelineState(
        request="read",
        workflow_state=WorkflowState(
            workflow_id="workflow-read", status=ExecutionStatus.RUNNING, total_steps=1
        ),
    )
    store = CheckpointStore(tmp_path)
    store.save_checkpoint(RecoveryCheckpoint(
        execution_id="read-only", principal_id="local-default", session_id="default",
        execution_state=state.model_dump(mode="json"),
        pipeline_state=pipeline.model_dump(mode="json"),
        operation_outcomes={"read-only:task:digest": "started"},
        recovery_safe=True,
    ))
    orchestrator = _Lifecycle()
    restarted = ExecutionCoordinator(orchestrator, checkpoint_store=CheckpointStore(tmp_path))
    assert restarted.inspect_execution("read-only").status == ExecutionStatus.RECOVERING
    assert await restarted.recover_pending() == ["read-only"]
    final = await restarted.wait_execution("read-only")
    assert final.execution_id == "read-only"
    assert final.status == ExecutionStatus.COMPLETED
    assert orchestrator.calls == 0
    assert orchestrator.resumed == 1


class _FlakyProvider(BaseProvider):
    def __init__(self):
        self.calls = 0

    @property
    def name(self):
        return "mock"

    async def execute(self, payload):
        self.calls += 1
        if self.calls == 1:
            return {"success": False, "message": "503 server error", "finish_reason": "server_error"}
        return {"success": True, "content": "recovered"}

    async def health_check(self):
        return True

    def supports(self, capability):
        return True


@pytest.mark.asyncio
async def test_exact_production_transient_provider_failure_retries_in_runtime(tmp_path, monkeypatch):
    provider_settings = ProviderSettings(
        _env_file=None, default_provider="mock", mock_agent=True,
        fallback_enabled=False, local_base_url="http://127.0.0.1:11434", local_model="local-test",
    )
    monkeypatch.setattr(core_app, "ProviderSettings", lambda: provider_settings)
    settings = Settings(
        _env_file=None, sqlite_url=f"sqlite:///{(tmp_path / 'p6.db').as_posix()}",
        personality_state_path=str(tmp_path / "personality.json"),
        checkpoint_location=str(tmp_path / "checkpoints"),
        runtime_retry_initial_delay_seconds=0,
    )
    orchestrator = create_orchestrator(settings)
    provider = _FlakyProvider()
    orchestrator.provider_registry.register("mock", provider, orchestrator.provider_registry.get_info("mock"))
    monkeypatch.setattr(orchestrator.health_checker, "is_available", lambda _provider: True)
    task = approved_task(task_id="exact-provider", action_type="text_generation", subject_id="exact-p6")
    result = await orchestrator.runtime.run(
        RuntimeContext(request_id="exact-p6"), task,
        RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="P6",
                        execution_constraints=task.permit.constraints),
    )
    assert result.status == TaskStatus.COMPLETED, (result.error, result.metadata, provider.calls)
    assert result.output["content"] == "recovered"
    assert result.metadata["retry_count"] == 1
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_exact_production_approval_checkpoint_resumes_once_after_restart(tmp_path, monkeypatch):
    provider_settings = ProviderSettings(
        _env_file=None, default_provider="mock", mock_agent=True,
        fallback_enabled=False, local_base_url="http://127.0.0.1:11434", local_model="local-test",
    )
    monkeypatch.setattr(core_app, "ProviderSettings", lambda: provider_settings)
    checkpoint_dir = tmp_path / "checkpoints"
    settings = Settings(
        _env_file=None, sqlite_url=f"sqlite:///{(tmp_path / 'restart.db').as_posix()}",
        personality_state_path=str(tmp_path / "personality.json"),
        checkpoint_location=str(checkpoint_dir),
    )
    orchestrator = create_orchestrator(settings)
    monkeypatch.setattr(orchestrator.health_checker, "is_available", lambda _provider: True)
    internet = orchestrator.tool_manager.resolve_tool("internet")
    calls = 0

    async def safe_search(arguments):
        nonlocal calls
        calls += 1
        return ToolResult(ok=True, data={"internet": True, "results": [{"title": "P6"}]})

    monkeypatch.setattr(internet, "run", safe_search)
    first = orchestrator.execution_coordinator
    waiting = await first.start_execution("Search the internet for P6 restart recovery")
    approval = first.pending_approval(waiting.execution_id)
    assert waiting.status == ExecutionStatus.AWAITING_APPROVAL

    restarted = ExecutionCoordinator(
        orchestrator,
        checkpoint_store=CheckpointStore(checkpoint_dir),
        execution_timeout_s=settings.execution_timeout_seconds,
    )
    restored = restarted.inspect_execution(waiting.execution_id)
    assert restored.status == ExecutionStatus.AWAITING_APPROVAL
    recovered_plan = restarted._executions[waiting.execution_id].pipeline_state.execution_plan
    recovered_plan_task = next(task for task in recovered_plan.tasks if task.task_id == approval["approval_id"])
    recovered_digest = recovered_plan_task.metadata["permit"]["operation_digest"]
    completed = await restarted.submit_approval(
        waiting.execution_id, approval["approval_id"], "allow"
    )
    result = restarted.result(waiting.execution_id)
    assert completed.status == ExecutionStatus.COMPLETED, (completed.error, result.error, result.metadata)
    assert calls == 1
    recovered_results = restarted._executions[waiting.execution_id].pipeline_state.workflow_state.results
    tool_result = next(item for item in recovered_results if item.task_id == approval["approval_id"])
    assert tool_result.metadata["operation_digest"] == recovered_digest
