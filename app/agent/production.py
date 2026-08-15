"""Production TUI adapter for the existing Samaktha orchestrator."""

from __future__ import annotations

import asyncio
import inspect
import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator
from uuid import uuid4

log = logging.getLogger(__name__)

from app.core.contracts.planning import TaskStatus
from app.core.contracts.runtime import RuntimeContext, RuntimeResult, RuntimeTask
from app.core.contracts.streaming import StreamEventType, StreamRequest
from app.core.orchestrator import SamakthaOrchestrator
from app.core.orchestrator.pipeline import PipelineState, PipelineEvent
from app.core.app import create_orchestrator
from app.agent.models import AgentEvent
from typing import Callable


from app.runtime.base import Runtime
from app.runtime.governance import enforce_cap_permit
from app.runtime.payload import build_provider_messages


def _result_text(result: RuntimeResult) -> str:
    """Extract the final user-facing text from a runtime result output."""
    output = result.output or {}
    for key in ("content", "response"):
        value = output.get(key, "")
        if isinstance(value, str) and value:
            return value
    return ""


class _StreamingRuntimeBridge(Runtime):
    """Runtime implementation that forwards provider tokens to a queue."""

    async def start(self) -> None:
        """Streaming bridge has no startup work."""
        return None

    async def stop(self) -> None:
        """Streaming bridge has no shutdown work."""
        return None

    def __init__(self, real_runtime: Any, streaming_executor: Any, output_queue: asyncio.Queue | None = None) -> None:
        self._real_runtime = real_runtime
        self._streaming = streaming_executor
        self._queue = output_queue

    def _queue_for(self, context: RuntimeContext) -> asyncio.Queue:
        """Per-execution output queue when one is supplied through context.

        The shared production orchestrator reuses one bridge instance across
        messages; each request carries its own queue so a single orchestrator
        can serve interleaved requests without mutable bridge state.
        """
        queue = (context.metadata or {}).get("output_queue")
        return queue if queue is not None else self._queue

    async def run(
        self,
        context: RuntimeContext,
        task: RuntimeTask,
        routing: Any,
    ) -> RuntimeResult:
        queue = self._queue_for(context)
        if task.action_type not in ("text_generation", "code_generation", "provider"):
            result = await self._real_runtime.run(context, task, routing)
            if result.status == TaskStatus.COMPLETED and result.output:
                action = task.metadata.get("action", task.action_type)
                if isinstance(result.output, dict) and "content" in result.output:
                    await queue.put({"type": "tool", "content": result.output["content"], "action": action})
                else:
                    await queue.put({"type": "tool", "content": result.output, "action": action})
            return result

        # Provider tasks stream through this bridge directly, so the CAP
        # permit gate must be enforced here rather than in the real runtime.
        started_at = datetime.now(timezone.utc)
        blocked = enforce_cap_permit(
            task,
            routing,
            started_at=started_at,
            duration_ms=0.0,
        )
        if blocked is not None:
            return blocked

        prompt = task.inputs.get("prompt", task.description)
        request = StreamRequest(
            request_id=context.request_id,
            provider_id=routing.provider_id,
            prompt=prompt,
            messages=build_provider_messages(task.inputs),
            capabilities=[task.action_type],
            metadata={"model_id": routing.model_id, "source": "tui"},
        )
        parts: list[str] = []
        try:
            async for chunk in self._streaming.stream_execute(request, context):
                if chunk.event_type == StreamEventType.TOKEN and chunk.content:
                    parts.append(chunk.content)
            joined = "".join(parts)
            log.debug("streamed generation buffered: %d chars", len(joined))
            return RuntimeResult(
                task_id=task.task_id,
                status=TaskStatus.COMPLETED,
                routing=routing,
                output={"content": joined},
            )
        except Exception as exc:
            return RuntimeResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                routing=routing,
                error=str(exc),
            )


class ProductionAgentRuntime:
    """UI-facing facade preserving the complete orchestration path.

    A single orchestrator instance is created once and reused for every
    message and resume — the same production pipeline the API serves. The
    per-request output queue travels through the runtime context so the
    streaming transport stays stateless and every request traverses the one
    shared orchestrator.
    """

    def __init__(self) -> None:
        base = create_orchestrator()
        self._streaming = base.streaming_executor
        self._base = base
        self._event_callback: Callable[[AgentEvent, dict[str, Any]], None] | None = None
        self._active_states: dict[str, PipelineState] = {}
        self._event_buses: dict[str, "RuntimeEventBus"] = {}
        bridge = _StreamingRuntimeBridge(
            base._runtime, self._streaming, output_queue=None
        )
        self._orchestrator = SamakthaOrchestrator(
            context_engine=self._base._context_engine,
            planner=self._base._planner,
            router=self._base._router,
            runtime=bridge,
            workflow_engine=self._base._workflow_engine,
            policy_engine=self._base._policy_engine,
            approval_engine=self._base._approval_engine,
            event_callback=self._orchestrator_event_handler,
            memory_manager=getattr(self._base, "memory_manager", None),
            memory_controller=getattr(self._base, "memory_controller", None),
            session_manager=getattr(self._base, "session_manager", None),
            conversation_state_manager=getattr(self._base, "conversation_state_manager", None),
            security_scanner=getattr(self._base, "input_scanner", None),
            security_output_filter=getattr(self._base, "output_filter", None),
        )

    def get_event_bus(self, session_id: str) -> "RuntimeEventBus":
        """Return the active RuntimeEventBus for a session."""
        from app.core.events import RuntimeEventBus
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

    def _orchestrator_event_handler(self, event: PipelineEvent) -> None:
        if event.type == "pause_requested" and self._event_callback:
            self._event_callback(
                AgentEvent.PAUSE_REQUESTED,
                {
                    "pause": event.pause.model_dump() if event.pause else {},
                    "task_id": event.task_id,
                    "data": event.data
                }
            )

    async def handle_message(
        self, session_id: str, user_input: str
    ) -> AsyncGenerator[Any, None]:
        output_queue: asyncio.Queue[str | None] = asyncio.Queue()
        await self.start()
        context = RuntimeContext(
            request_id=f"tui-{uuid4().hex}",
            session_id=session_id,
            metadata={"source": "tui", "streaming": True, "output_queue": output_queue},
        )

        async def run_pipeline() -> None:
            try:
                state = await self._orchestrator.run_pipeline(user_input, context)
                self._active_states[session_id] = state
                if state.runtime_result:
                    if state.runtime_result.error and state.runtime_result.status != TaskStatus.PAUSED:
                        await output_queue.put({"type": "error", "content": f"⚠ {state.runtime_result.error}"})
                    content = _result_text(state.runtime_result)
                    if content:
                        await output_queue.put({"type": "provider", "content": content})
            except Exception as exc:
                await output_queue.put({"type": "error", "content": f"⚠ {exc}"})
            finally:
                await output_queue.put(None)

        context.event_bus = self.get_event_bus(session_id)

        task = asyncio.create_task(run_pipeline())
        while True:
            item = await output_queue.get()
            if item is None:
                break
            yield item
        await task

    async def resume(self, session_id: str, task_id: str, updates: dict) -> AsyncGenerator[Any, None]:
        log.debug("User clicks Allow. resume() in ProductionAgentRuntime is invoked with task_id=%s", task_id)
        state = self._active_states.get(session_id)
        if not state:
            yield "⚠ Cannot resume: no active state found."
            return

        output_queue: asyncio.Queue[str | None] = asyncio.Queue()
        context = RuntimeContext(
            request_id=f"tui-resume-{uuid4().hex}",
            session_id=session_id,
            metadata={"source": "tui", "streaming": True, "output_queue": output_queue},
        )

        async def run_pipeline() -> None:
            try:
                log.debug("resume() calling resume_pipeline()")
                state_new = await self._orchestrator.resume_pipeline(state, context, task_id, updates)
                log.debug("resume() received state from resume_pipeline(), runtime_result=%s", state_new.runtime_result)
                self._active_states[session_id] = state_new
                if state_new.runtime_result:
                    if state_new.runtime_result.error and state_new.runtime_result.status != TaskStatus.PAUSED:
                        await output_queue.put({"type": "error", "content": f"⚠ {state_new.runtime_result.error}"})
                    content = _result_text(state_new.runtime_result)
                    if content:
                        await output_queue.put({"type": "provider", "content": content})
                log.debug("The first RuntimeResult is yielded: %s", state_new.runtime_result)
            except Exception as exc:
                await output_queue.put({"type": "error", "content": f"⚠ {exc}"})
            finally:
                await output_queue.put(None)

        context.event_bus = self.get_event_bus(session_id)

        task = asyncio.create_task(run_pipeline())
        while True:
            item = await output_queue.get()
            if item is None:
                break
            yield item
        await task


def build_production_runtime() -> ProductionAgentRuntime:
    return ProductionAgentRuntime()
