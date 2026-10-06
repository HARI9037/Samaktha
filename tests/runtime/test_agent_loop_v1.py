from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.agent_loop import AgentLoop
from app.core.contracts import (
    AgentState,
    ObservationStatus,
    RuntimeContext,
    RuntimeResult,
    RuntimeTask,
    TaskStatus,
    TerminationState,
)
from app.core.events import RuntimeEventBus, RuntimeEventType
from app.core.contracts.policy import (
    ActionRisk,
    ApprovalDecision,
    ExecutionConstraints,
    ExecutionPermit,
    PrivacyCategory,
)
from app.runtime.base import Runtime


def action() -> RuntimeTask:
    return RuntimeTask(
        task_id="task-1",
        title="write",
        description="write one file",
        action_type="write_resource",
        metadata={"step_id": "step-1", "action_id": "action-1"},
    )


def state() -> AgentState:
    return AgentState(
        session_id="session-1", task_id="task-1", turn_id="turn-1",
        trace_id="trace-1", current_step_id="step-1", pending_action=action(),
    )


def permit() -> ExecutionPermit:
    return ExecutionPermit(
        permit_id="permit-1", action_id="action-1", issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc), subject_id="test", operation_digest="digest",
        action_type="write_resource", target=None, risk=ActionRisk.LOW,
        constraints=ExecutionConstraints(privacy_category=PrivacyCategory.PUBLIC),
        policy_reference="test", approval_source="test", decision=ApprovalDecision.ALLOW,
        integrity_digest="test",
    )


class FakeRuntime(Runtime):
    def __init__(self, result: RuntimeResult):
        self.result = result
        self.calls = 0

    async def start(self):
        pass

    async def stop(self):
        pass

    async def run(self, context, task, routing):
        self.calls += 1
        assert task.metadata["permit_id"] == "permit-1"
        assert task.metadata["permit"]["permit_id"] == "permit-1"
        return self.result


class RaisingRuntime(FakeRuntime):
    async def run(self, context, task, routing):
        self.calls += 1
        raise RuntimeError("provider token=super-secret-value failed")


def result(status: TaskStatus, *, verified: bool = True, error: str | None = None) -> RuntimeResult:
    return RuntimeResult(
        task_id="task-1", status=status, error=error,
        output={"verified": verified}, metadata={"verified": verified},
    )


@pytest.mark.asyncio
async def test_success_observes_updates_and_terminates_once():
    runtime = FakeRuntime(result(TaskStatus.COMPLETED))
    loop = AgentLoop(runtime=runtime, permit_evaluator=lambda _: permit())

    updated, observation, transition = await loop.run(state(), RuntimeContext(request_id="request-1"))

    assert runtime.calls == 1
    assert observation.status is ObservationStatus.SUCCEEDED
    assert observation.task_id == observation.action_id.replace("action", "task")
    assert updated.termination is TerminationState.COMPLETED
    assert updated.completed_step_ids == ["step-1"]
    assert transition.to_termination is TerminationState.COMPLETED


@pytest.mark.asyncio
async def test_failure_does_not_claim_success():
    runtime = FakeRuntime(result(TaskStatus.FAILED, verified=False, error="disk full"))
    updated, observation, _ = await AgentLoop(
        runtime=runtime, permit_evaluator=lambda _: permit()
    ).run(state(), RuntimeContext(request_id="request-1"))

    assert observation.status is ObservationStatus.FAILED
    assert updated.termination is TerminationState.FAILED
    assert not updated.completed_step_ids


@pytest.mark.asyncio
async def test_denial_does_not_execute_runtime():
    runtime = FakeRuntime(result(TaskStatus.COMPLETED))
    updated, observation, _ = await AgentLoop(
        runtime=runtime, permit_evaluator=lambda _: None
    ).run(state(), RuntimeContext(request_id="request-1"))

    assert runtime.calls == 0
    assert observation.status is ObservationStatus.DENIED
    assert updated.termination is TerminationState.DENIED


@pytest.mark.asyncio
async def test_unverified_result_is_not_success():
    runtime = FakeRuntime(result(TaskStatus.COMPLETED, verified=False))
    updated, observation, _ = await AgentLoop(
        runtime=runtime, permit_evaluator=lambda _: permit()
    ).run(state(), RuntimeContext(request_id="request-1"))

    assert observation.status is ObservationStatus.UNVERIFIED
    assert updated.termination is TerminationState.UNVERIFIED
    assert not updated.completed_step_ids


@pytest.mark.asyncio
async def test_cancelled_result_terminates():
    runtime = FakeRuntime(result(TaskStatus.CANCELLED, verified=False))
    updated, observation, _ = await AgentLoop(
        runtime=runtime, permit_evaluator=lambda _: permit()
    ).run(state(), RuntimeContext(request_id="request-1"))

    assert observation.status is ObservationStatus.CANCELLED
    assert updated.termination is TerminationState.CANCELLED


@pytest.mark.asyncio
async def test_hard_one_step_limit_prevents_second_execution():
    runtime = FakeRuntime(result(TaskStatus.COMPLETED))
    loop = AgentLoop(runtime=runtime, permit_evaluator=lambda _: permit())
    updated, _, _ = await loop.run(state(), RuntimeContext(request_id="request-1"))

    with pytest.raises(ValueError, match="terminal"):
        await loop.run(updated, RuntimeContext(request_id="request-1"))
    assert runtime.calls == 1


@pytest.mark.asyncio
async def test_runtime_exception_becomes_sanitized_failed_observation():
    runtime = RaisingRuntime(result(TaskStatus.COMPLETED))
    updated, observation, _ = await AgentLoop(
        runtime=runtime, permit_evaluator=lambda _: permit()
    ).run(state(), RuntimeContext(request_id="request-1"))

    assert observation.status is ObservationStatus.FAILED
    assert observation.failure.code == "RuntimeError"
    assert "super-secret-value" not in observation.failure.message
    assert observation.failure.message == "provider token=[REDACTED] failed"
    assert observation.task_id == "task-1"
    assert observation.turn_id == "turn-1"
    assert observation.action_id == "action-1"
    assert observation.permit_id == "permit-1"
    assert observation.trace_id == "trace-1"
    assert updated.termination is TerminationState.FAILED


@pytest.mark.asyncio
async def test_event_order_observation_and_state_follow_runtime():
    runtime = FakeRuntime(result(TaskStatus.COMPLETED))
    bus = RuntimeEventBus("session-1")
    updated, _, _ = await AgentLoop(
        runtime=runtime, permit_evaluator=lambda _: permit()
    ).run(state(), RuntimeContext(request_id="request-1", event_bus=bus))
    # Event dispatch is fire-and-forget; history is synchronous and ordered.
    events = [event.data.event_type for event in bus.history()]
    assert events.index(RuntimeEventType.TASK_STARTED) < events.index(RuntimeEventType.CAP_COMPLETED)
    assert events.index(RuntimeEventType.EXECUTION_COMPLETED) < events.index(RuntimeEventType.OBSERVATION_CREATED)
    assert events.index(RuntimeEventType.OBSERVATION_CREATED) < events.index(RuntimeEventType.STATE_UPDATED)
    assert events[-1] is RuntimeEventType.TASK_COMPLETED
    assert updated.termination is TerminationState.COMPLETED
