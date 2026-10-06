"""Small, typed contracts for the first Samaktha agent-loop increment.

These models deliberately describe orchestration state only.  Conversation,
Runtime, memory, and artifact stores remain owned by their existing modules.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.core.contracts.planning import ExecutionPlan, TaskStatus
from app.core.contracts.runtime import RuntimeResult, RuntimeTask


class ObservationStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    CANCELLED = "cancelled"
    PARTIAL = "partial"
    UNVERIFIED = "unverified"


class TerminationState(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"
    CANCELLED = "cancelled"
    UNVERIFIED = "unverified"
    PARTIAL = "partial"


class VerificationRecord(BaseModel):
    """Deterministic verification evidence copied from Runtime output."""

    verified: bool = False
    reason: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class FailureRecord(BaseModel):
    code: str | None = None
    message: str
    retryable: bool = False


class Observation(BaseModel):
    """One immutable interpretation of one Runtime result.

    The adapter is the only component that creates this from execution
    evidence.  No model-generated response is accepted as evidence here.
    """

    observation_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    turn_id: str
    step_id: str
    action_id: str
    permit_id: str | None = None
    trace_id: str | None = None
    status: ObservationStatus
    executed_action: RuntimeTask | None = None
    runtime_result: RuntimeResult | None = None
    failure: FailureRecord | None = None
    verification: VerificationRecord = Field(default_factory=VerificationRecord)
    side_effects: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StateTransition(BaseModel):
    """Deterministic state change caused by one Observation."""

    transition_id: str = Field(default_factory=lambda: str(uuid4()))
    observation_id: str
    from_termination: TerminationState
    to_termination: TerminationState
    completed_step_id: str | None = None
    failed_step_id: str | None = None
    applied_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentState(BaseModel):
    """Orchestration state for the one-step loop; not a replacement state store."""

    session_id: str
    task_id: str
    turn_id: str
    trace_id: str | None = None
    current_plan: ExecutionPlan | None = None
    current_step_id: str | None = None
    pending_action: RuntimeTask | None = None
    permit_id: str | None = None
    completed_step_ids: list[str] = Field(default_factory=list)
    failed_step_ids: list[str] = Field(default_factory=list)
    last_observation: Observation | None = None
    failures: list[FailureRecord] = Field(default_factory=list)
    artifact_references: list[str] = Field(default_factory=list)
    termination: TerminationState = TerminationState.RUNNING
    iterations: int = 0


def _verification_from(result: RuntimeResult) -> VerificationRecord:
    output = result.output or {}
    metadata = result.metadata or {}
    refs = list(metadata.get("evidence_refs") or output.get("evidence_refs") or [])
    verified = bool(metadata.get("verified", output.get("verified", False)))
    reason = metadata.get("verification_reason") or output.get("verification_reason")
    return VerificationRecord(verified=verified, reason=reason, evidence_refs=refs)


def observation_from_runtime(
    *,
    action: RuntimeTask,
    result: RuntimeResult,
    turn_id: str,
    step_id: str,
    action_id: str,
    permit_id: str | None = None,
    trace_id: str | None = None,
) -> Observation:
    """Convert actual Runtime evidence into one Observation."""
    verification = _verification_from(result)
    if result.status == TaskStatus.CANCELLED:
        status = ObservationStatus.CANCELLED
    elif result.status == TaskStatus.COMPLETED:
        status = ObservationStatus.SUCCEEDED if verification.verified else ObservationStatus.UNVERIFIED
    elif result.status == TaskStatus.FAILED:
        status = ObservationStatus.FAILED
    elif result.status == TaskStatus.PAUSED:
        status = ObservationStatus.PARTIAL
    else:
        status = ObservationStatus.FAILED

    failure = None
    if status in {ObservationStatus.FAILED, ObservationStatus.UNVERIFIED}:
        failure = FailureRecord(
            code=(result.metadata or {}).get("failure_type"),
            message=result.error or verification.reason or "Runtime did not complete the action.",
        )
    return Observation(
        task_id=action.task_id,
        turn_id=turn_id,
        step_id=step_id,
        action_id=action_id,
        permit_id=permit_id,
        trace_id=trace_id,
        status=status,
        executed_action=action,
        runtime_result=result,
        failure=failure,
        verification=verification,
        side_effects=list((result.metadata or {}).get("side_effects") or []),
        evidence_refs=verification.evidence_refs,
    )


def denied_observation(
    *, action: RuntimeTask, turn_id: str, step_id: str, action_id: str, trace_id: str | None = None
) -> Observation:
    return Observation(
        task_id=action.task_id,
        turn_id=turn_id,
        step_id=step_id,
        action_id=action_id,
        trace_id=trace_id,
        status=ObservationStatus.DENIED,
        executed_action=None,
        failure=FailureRecord(code="governance_denied", message="CAP denied the action."),
    )


def apply_observation(state: AgentState, observation: Observation) -> tuple[AgentState, StateTransition]:
    """Apply one deterministic observation; never retries or replans."""
    before = state.termination
    state = state.model_copy(deep=True)
    state.last_observation = observation
    state.iterations += 1
    state.pending_action = None
    if observation.failure:
        state.failures.append(observation.failure)

    if observation.status == ObservationStatus.SUCCEEDED and observation.verification.verified:
        state.completed_step_ids.append(observation.step_id)
        state.termination = TerminationState.COMPLETED
        completed = observation.step_id
        failed = None
    elif observation.status == ObservationStatus.DENIED:
        state.termination = TerminationState.DENIED
        completed = failed = None
    elif observation.status == ObservationStatus.CANCELLED:
        state.termination = TerminationState.CANCELLED
        completed = failed = None
    elif observation.status == ObservationStatus.PARTIAL:
        state.termination = TerminationState.PARTIAL
        completed = failed = None
    elif observation.status == ObservationStatus.UNVERIFIED:
        state.termination = TerminationState.UNVERIFIED
        completed = failed = None
    else:
        state.failed_step_ids.append(observation.step_id)
        state.termination = TerminationState.FAILED
        completed = None
        failed = observation.step_id

    return state, StateTransition(
        observation_id=observation.observation_id,
        from_termination=before,
        to_termination=state.termination,
        completed_step_id=completed,
        failed_step_id=failed,
    )
