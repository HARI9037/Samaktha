"""Reversible one-step agent loop built on Samaktha CAP and Runtime seams."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
import re
from typing import Any

from app.core.contracts.agent_loop import (
    AgentState,
    Observation,
    ObservationStatus,
    StateTransition,
    TerminationState,
    apply_observation,
    denied_observation,
    observation_from_runtime,
)
from app.core.contracts.policy import ExecutionPermit
from app.core.contracts.runtime import RuntimeContext, RuntimeResult, RuntimeTask
from app.core.events import RuntimeEventBus, RuntimeEventType
from app.runtime.base import Runtime


PermitEvaluator = Callable[[RuntimeTask], Awaitable[ExecutionPermit | None] | ExecutionPermit | None]


class AgentLoop:
    """Execute exactly one already-planned action, then terminate."""

    def __init__(
        self,
        *,
        runtime: Runtime,
        permit_evaluator: PermitEvaluator,
        max_steps: int = 1,
    ) -> None:
        if max_steps < 1:
            raise ValueError("AgentLoop max_steps must be positive")
        self._runtime = runtime
        self._permit_evaluator = permit_evaluator
        self._max_steps = max_steps

    async def run(self, state: AgentState, context: RuntimeContext) -> tuple[AgentState, Observation, StateTransition]:
        if state.termination != TerminationState.RUNNING:
            raise ValueError("AgentLoop cannot execute a terminal AgentState")
        if state.iterations >= self._max_steps:
            raise ValueError("AgentLoop step limit reached before execution")
        action = state.pending_action
        if action is None:
            raise ValueError("AgentLoop requires one pending RuntimeTask")
        step_id = state.current_step_id or action.metadata.get("step_id") or action.task_id
        action_id = action.metadata.get("action_id") or action.task_id
        trace_id = state.trace_id or context.request_id
        self._publish(context.event_bus, RuntimeEventType.TASK_STARTED, state, action_id)

        permit = self._permit_evaluator(action)
        if hasattr(permit, "__await__"):
            permit = await permit
        if permit is None:
            observation = denied_observation(
                action=action, turn_id=state.turn_id, step_id=step_id,
                action_id=action_id, trace_id=trace_id,
            )
            self._publish(context.event_bus, RuntimeEventType.CAP_DENIED, state, action_id)
        else:
            state.permit_id = permit.permit_id
            action = action.model_copy(update={
                "metadata": {
                    **action.metadata,
                    "permit": permit.model_dump(mode="json"),
                    "permit_id": permit.permit_id,
                    "required_permissions": [scope.value for scope in permit.required_permissions],
                    "execution_constraints": permit.constraints.model_dump(mode="json"),
                    "_cap_permit": permit.model_dump(mode="json"),
                }
            })
            self._publish(context.event_bus, RuntimeEventType.CAP_COMPLETED, state, action_id)
            self._publish(context.event_bus, RuntimeEventType.EXECUTION_CREATED, state, action_id, "started")
            try:
                result = await self._runtime.run(context, action, context.metadata.get("routing"))
                self._publish(
                    context.event_bus,
                    RuntimeEventType.EXECUTION_COMPLETED
                    if result.status.value == "completed"
                    else RuntimeEventType.EXECUTION_FAILED,
                    state,
                    action_id,
                    result.status.value,
                )
                observation = observation_from_runtime(
                    action=action, result=result, turn_id=state.turn_id, step_id=step_id,
                    action_id=action_id, permit_id=permit.permit_id, trace_id=trace_id,
                )
            except Exception as exc:
                observation = Observation(
                    task_id=action.task_id,
                    turn_id=state.turn_id,
                    step_id=step_id,
                    action_id=action_id,
                    permit_id=permit.permit_id,
                    trace_id=trace_id,
                    status=ObservationStatus.FAILED,
                    executed_action=action,
                    failure={
                        "code": type(exc).__name__,
                        "message": _sanitize_error(str(exc)),
                    },
                )
                self._publish(context.event_bus, RuntimeEventType.EXECUTION_FAILED, state, action_id, "failed")

        updated, transition = apply_observation(state, observation)
        self._publish(context.event_bus, RuntimeEventType.OBSERVATION_CREATED, state, action_id, observation.status.value)
        self._publish(context.event_bus, RuntimeEventType.STATE_UPDATED, updated, action_id, updated.termination.value)
        self._publish(
            context.event_bus,
            RuntimeEventType.TASK_COMPLETED
            if observation.status is ObservationStatus.SUCCEEDED
            else RuntimeEventType.TASK_FAILED,
            updated,
            action_id,
            observation.status.value,
        )
        return updated, observation, transition

    @staticmethod
    def _publish(bus: Any, event_type: RuntimeEventType, state: AgentState, action_id: str, status: str = "started") -> None:
        if isinstance(bus, RuntimeEventBus):
            bus.publish(
                event_type, subsystem="agent_loop", status=status,
                trace_id=state.trace_id, task_id=state.task_id,
                payload={"turn_id": state.turn_id, "action_id": action_id},
            )


def _sanitize_error(message: str) -> str:
    """Keep exception category while removing common credential-shaped data."""
    sanitized = re.sub(
        r"(?i)(api[_-]?key|password|secret|token|private[_-]?key)\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        message,
    )
    return sanitized[:500] or "Runtime execution failed."
