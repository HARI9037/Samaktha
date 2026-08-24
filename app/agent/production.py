"""Production TUI adapter for the existing Samaktha orchestrator."""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, AsyncGenerator
from uuid import uuid4

log = logging.getLogger(__name__)

from app.core.contracts.planning import TaskStatus
from app.core.contracts.runtime import RuntimeResult
from app.core.contracts.memory import DEFAULT_LOCAL_PRINCIPAL_ID
from app.core.events import RuntimeEvent, RuntimeEventBus, RuntimeEventType
from app.core.app import create_orchestrator
from app.core.execution_coordinator import ExecutionCoordinator
from app.agent.models import AgentEvent
from typing import Callable


def _result_text(result: RuntimeResult) -> str:
    """Extract the final user-facing text from a runtime result output."""
    output = result.output or {}
    for key in ("content", "response"):
        value = output.get(key, "")
        if isinstance(value, str) and value:
            return value
    return ""


async def _enqueue_runtime_result(
    queue: asyncio.Queue,
    result: RuntimeResult,
) -> None:
    if result.error and result.status != TaskStatus.PAUSED:
        await queue.put({"type": "error", "content": f"⚠ {result.error}"})
    content = _result_text(result)
    if content:
        await queue.put({"type": "provider", "content": content})
    elif result.output and result.metadata.get("tool"):
        await queue.put({
            "type": "tool",
            "content": result.output,
            "action": result.metadata.get("action", result.metadata["tool"]),
        })


class ProductionAgentRuntime:
    """UI-facing facade preserving the complete orchestration path.

    A single coordinator/orchestrator composition is reused for every message
    and approval.  The adapter only renders canonical execution events and
    results; it owns no PipelineState or provider execution path.
    """

    def __init__(self, orchestrator: Any | None = None) -> None:
        base = orchestrator or create_orchestrator()
        self._base = base
        self._event_callback: Callable[[AgentEvent, dict[str, Any]], None] | None = None
        self._coordinator = getattr(
            base, "execution_coordinator", ExecutionCoordinator(base)
        )
        self._session_executions: dict[str, str] = {}
        self._event_buses: dict[str, RuntimeEventBus] = {}
        self._orchestrator = base

    def get_event_bus(self, session_id: str) -> "RuntimeEventBus":
        """Return the active RuntimeEventBus for a session."""
        if session_id not in self._event_buses:
            self._event_buses[session_id] = RuntimeEventBus(session_id)
        return self._event_buses[session_id]

    async def start(self) -> None:
        """Start the shared reminder scheduler (idempotent)."""
        scheduler = getattr(self._base, "reminder_scheduler", None)
        if scheduler is not None and inspect.iscoroutinefunction(
            getattr(scheduler, "start", None)
        ):
            await scheduler.start()

    async def stop(self) -> None:
        """Gracefully stop the shared reminder scheduler."""
        scheduler = getattr(self._base, "reminder_scheduler", None)
        if scheduler is not None and inspect.iscoroutinefunction(
            getattr(scheduler, "stop", None)
        ):
            await scheduler.stop()

    async def handle_message(
        self, session_id: str, user_input: str
    ) -> AsyncGenerator[Any, None]:
        output_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        await self.start()
        bus = self.get_event_bus(session_id)
        execution_id = f"tui-{uuid4().hex}"
        token_seen = False

        def on_event(event: RuntimeEvent) -> None:
            nonlocal token_seen
            if (
                event.data.execution_id == execution_id
                and event.data.event_type == RuntimeEventType.TOKEN
            ):
                token_seen = True
                content = event.data.payload.get("content", "")
                if content:
                    output_queue.put_nowait({"type": "provider", "content": content})

        async def run_pipeline() -> None:
            subscription = bus.subscribe(on_event)
            try:
                state = await self._coordinator.start_execution(
                    user_input,
                    principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
                    session_id=session_id,
                    source="tui",
                    streaming=True,
                    wait=True,
                    event_bus=bus,
                    execution_id=execution_id,
                )
                self._session_executions[session_id] = state.execution_id
                result = self._coordinator.result(
                    state.execution_id,
                    principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
                )
                if result is not None and not token_seen:
                    await _enqueue_runtime_result(output_queue, result)
                if state.status.value == "awaiting_approval":
                    approval = self._coordinator.pending_approval(
                        state.execution_id,
                        principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
                    )
                    if approval and self._event_callback:
                        self._event_callback(
                            AgentEvent.PAUSE_REQUESTED,
                            {
                                "pause": {
                                    "reason": approval["reason"],
                                    "metadata": approval["metadata"],
                                },
                                "task_id": approval["approval_id"],
                                "execution_id": state.execution_id,
                                "data": {},
                            },
                        )
            except Exception as exc:
                await output_queue.put({"type": "error", "content": f"⚠ {exc}"})
            finally:
                bus.unsubscribe(subscription)
                await output_queue.put(None)

        task = asyncio.create_task(run_pipeline())
        while True:
            item = await output_queue.get()
            if item is None:
                break
            yield item
        await task

    async def resume(self, session_id: str, task_id: str, updates: dict) -> AsyncGenerator[Any, None]:
        log.debug("User clicks Allow. resume() in ProductionAgentRuntime is invoked with task_id=%s", task_id)
        execution_id = self._session_executions.get(session_id)
        if not execution_id:
            yield "⚠ Cannot resume: no active state found."
            return

        output_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        bus = self.get_event_bus(session_id)
        token_seen = False

        def on_event(event: RuntimeEvent) -> None:
            nonlocal token_seen
            if (
                event.data.execution_id == execution_id
                and event.data.event_type == RuntimeEventType.TOKEN
            ):
                token_seen = True
                content = event.data.payload.get("content", "")
                if content:
                    output_queue.put_nowait({"type": "provider", "content": content})

        async def run_pipeline() -> None:
            subscription = bus.subscribe(on_event)
            try:
                decision = str(updates.get("approval_decision", "deny"))
                state = await self._coordinator.submit_approval(
                    execution_id,
                    task_id,
                    decision,
                    principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
                    reasons=list(updates.get("approval_reasons", [])),
                    source="tui",
                )
                result = self._coordinator.result(
                    execution_id, principal_id=DEFAULT_LOCAL_PRINCIPAL_ID
                )
                if result is not None and not token_seen:
                    await _enqueue_runtime_result(output_queue, result)
            except Exception as exc:
                await output_queue.put({"type": "error", "content": f"⚠ {exc}"})
            finally:
                bus.unsubscribe(subscription)
                await output_queue.put(None)

        task = asyncio.create_task(run_pipeline())
        while True:
            item = await output_queue.get()
            if item is None:
                break
            yield item
        await task

    def active_execution_id(self, session_id: str) -> str | None:
        return self._session_executions.get(session_id)

    async def cancel(self, session_id: str):
        execution_id = self._session_executions.get(session_id)
        if execution_id is None:
            return None
        return await self._coordinator.cancel_execution(
            execution_id, principal_id=DEFAULT_LOCAL_PRINCIPAL_ID
        )


def build_production_runtime() -> ProductionAgentRuntime:
    return ProductionAgentRuntime()
