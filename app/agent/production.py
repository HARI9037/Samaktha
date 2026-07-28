"""Production TUI adapter for the existing Samaktha orchestrator."""

from __future__ import annotations

import asyncio
import logging
import tempfile
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

class _StreamingRuntimeBridge(Runtime):
    """Runtime implementation that forwards provider tokens to a queue."""

    async def start(self) -> None:
        """Streaming bridge has no startup work."""
        return None

    async def stop(self) -> None:
        """Streaming bridge has no shutdown work."""
        return None

    def __init__(self, real_runtime: Any, streaming_executor: Any, output_queue: asyncio.Queue) -> None:
        self._real_runtime = real_runtime
        self._streaming = streaming_executor
        self._queue = output_queue

    async def run(
        self,
        context: RuntimeContext,
        task: RuntimeTask,
        routing: Any,
    ) -> RuntimeResult:
        if task.action_type not in ("text_generation", "code_generation", "provider"):
            result = await self._real_runtime.run(context, task, routing)
            if result.status == TaskStatus.COMPLETED and result.output:
                action = task.metadata.get("action", task.action_type)
                if isinstance(result.output, dict) and "content" in result.output:
                    await self._queue.put({"type": "tool", "content": result.output["content"], "action": action})
                else:
                    await self._queue.put({"type": "tool", "content": result.output, "action": action})
            return result

        prompt = task.inputs.get("prompt", task.description)
        request = StreamRequest(
            request_id=context.request_id,
            provider_id=routing.provider_id,
            prompt=prompt,
            capabilities=[task.action_type],
            metadata={"model_id": routing.model_id, "source": "tui"},
        )
        parts: list[str] = []
        _first_token = False
        try:
            async for chunk in self._streaming.stream_execute(request, context):
                if chunk.event_type == StreamEventType.TOKEN and chunk.content:
                    if not _first_token:
                        log.debug("first streamed token reaches TUI: %r", chunk.content)
                        _first_token = True
                    parts.append(chunk.content)
                    await self._queue.put({"type": "provider", "content": chunk.content})
            return RuntimeResult(
                task_id=task.task_id,
                status=TaskStatus.COMPLETED,
                routing=routing,
                output={"content": "".join(parts)},
            )
        except Exception as exc:
            return RuntimeResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                routing=routing,
                error=str(exc),
            )


class ProductionAgentRuntime:
    """UI-facing facade preserving the complete orchestration path."""

    def __init__(self) -> None:
        base = create_orchestrator()
        self._streaming = base.streaming_executor
        self._base = base
        self._event_callback: Callable[[AgentEvent, dict[str, Any]], None] | None = None
        self._active_states: dict[str, PipelineState] = {}
        
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
        try:
            trace_path = tempfile.gettempdir() + "/samaktha_trace.txt"
            with open(trace_path, "a", encoding="utf-8") as f:
                f.write("[TRACE] handle_message\n")
        except OSError:
            pass
        output_queue: asyncio.Queue[str | None] = asyncio.Queue()
        bridge = _StreamingRuntimeBridge(self._base._runtime, self._streaming, output_queue)
        orchestrator = SamakthaOrchestrator(
            context_engine=self._base._context_engine,
            planner=self._base._planner,
            router=self._base._router,
            runtime=bridge,
            workflow_engine=self._base._workflow_engine,
            policy_engine=self._base._policy_engine,
            approval_engine=self._base._approval_engine,
            event_callback=self._orchestrator_event_handler,
        )
        context = RuntimeContext(
            request_id=f"tui-{uuid4().hex}",
            session_id=session_id,
            metadata={"source": "tui", "streaming": True},
        )

        async def run_pipeline() -> None:
            try:
                state = await orchestrator.run_pipeline(user_input, context)
                self._active_states[session_id] = state
                if state.runtime_result and state.runtime_result.error and state.runtime_result.status != TaskStatus.PAUSED:
                    await output_queue.put({"type": "error", "content": f"⚠ {state.runtime_result.error}"})
            except Exception as exc:
                await output_queue.put({"type": "error", "content": f"⚠ {exc}"})
            finally:
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
        state = self._active_states.get(session_id)
        if not state:
            yield "⚠ Cannot resume: no active state found."
            return
            
        output_queue: asyncio.Queue[str | None] = asyncio.Queue()
        bridge = _StreamingRuntimeBridge(self._base._runtime, self._streaming, output_queue)
        orchestrator = SamakthaOrchestrator(
            context_engine=self._base._context_engine,
            planner=self._base._planner,
            router=self._base._router,
            runtime=bridge,
            workflow_engine=self._base._workflow_engine,
            policy_engine=self._base._policy_engine,
            approval_engine=self._base._approval_engine,
            event_callback=self._orchestrator_event_handler,
        )
        context = RuntimeContext(
            request_id=f"tui-resume-{uuid4().hex}",
            session_id=session_id,
            metadata={"source": "tui", "streaming": True},
        )
        
        async def run_pipeline() -> None:
            try:
                log.debug("resume() calling resume_pipeline()")
                state_new = await orchestrator.resume_pipeline(state, context, task_id, updates)
                log.debug("resume() received state from resume_pipeline(), runtime_result=%s", state_new.runtime_result)
                self._active_states[session_id] = state_new
                if state_new.runtime_result and state_new.runtime_result.error and state_new.runtime_result.status != TaskStatus.PAUSED:
                    await output_queue.put({"type": "error", "content": f"⚠ {state_new.runtime_result.error}"})
                log.debug("The first RuntimeResult is yielded: %s", state_new.runtime_result)
            except Exception as exc:
                await output_queue.put({"type": "error", "content": f"⚠ {exc}"})
            finally:
                await output_queue.put(None)
                
        task = asyncio.create_task(run_pipeline())
        while True:
            item = await output_queue.get()
            if item is None:
                break
            yield item
        await task


def build_production_runtime() -> ProductionAgentRuntime:
    return ProductionAgentRuntime()
