from __future__ import annotations

from typing import Any, Protocol
import logging

from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeResult, RuntimeTask
from app.core.contracts.planning import TaskStatus
from app.core.contracts.pause import ExecutionPause
from app.core.contracts.protocols import (
    ProviderManagerLike,
    ToolManagerLike,
)

log = logging.getLogger(__name__)


class Executor(Protocol):
    """Runtime-local interface for task executors."""

    async def execute(
        self,
        context: RuntimeContext,
        task: RuntimeTask,
        routing: RoutingDecision,
    ) -> RuntimeResult:
        raise NotImplementedError


class ProviderExecutor:
    """Executes provider-backed runtime tasks through a registered provider."""

    def __init__(self, provider_manager: ProviderManagerLike) -> None:
        self._provider_manager = provider_manager

    async def execute(
        self,
        context: RuntimeContext,
        task: RuntimeTask,
        routing: RoutingDecision,
    ) -> RuntimeResult:
        log.debug("ProviderExecutor.execute() starts for task_id=%s", task.task_id)
        if context and context.trace:
            context.trace.add_event(
                source="runtime",
                event_type="runtime.provider.started",
                task_id=task.task_id,
                provider_id=routing.provider_id if routing else task.action_type,
                model_id=routing.model_id if routing else None
            )
            
        import time
        started_at = time.perf_counter()

        log.info(
            "Provider selection | provider=%s model=%s reason=router decision streaming=disabled",
            routing.provider_id if routing else task.action_type,
            routing.model_id if routing else "default",
        )
        
        try:
            output = await self._provider_manager.execute_provider(
                provider_id=routing.provider_id,
                payload=task.inputs,
                model_id=routing.model_id,
                required_capabilities=[task.action_type],
            )
            status = (
                TaskStatus.COMPLETED
                if output.get("success", True)
                else TaskStatus.FAILED
            )
            
            result = RuntimeResult(
                task_id=task.task_id,
                status=status,
                routing=routing,
                output=(
                    output.get("metadata", {}).get("legacy_response")
                    if output.get("metadata", {}).get("legacy_response")
                    else output
                ) if status == TaskStatus.COMPLETED else {},
                error=output.get("message") if status == TaskStatus.FAILED else None,
            )
        except Exception as e:
            result = RuntimeResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                routing=routing,
                error=str(e),
            )
            
        if context and context.trace:
            context.trace.add_event(
                source="runtime",
                event_type="runtime.provider.completed" if result.status == TaskStatus.COMPLETED else "runtime.provider.failed",
                duration_ms=(time.perf_counter() - started_at) * 1000,
                task_id=task.task_id,
            )
            
        return result


class ToolExecutor:
    """Executes tool-backed runtime tasks through a registered tool."""

    def __init__(self, tool_manager: ToolManagerLike) -> None:
        self._tool_manager = tool_manager

    async def execute(
        self,
        context: RuntimeContext,
        task: RuntimeTask,
        routing: RoutingDecision,
    ) -> RuntimeResult:
        log.debug("ToolExecutor.execute() starts for task_id=%s with action_type=%s", task.task_id, task.action_type)
        tool_id = task.metadata.get("tool") if task.action_type == "tool" else task.action_type

        if context and context.trace:
            context.trace.add_event(
                source="runtime",
                event_type="runtime.tool.started",
                task_id=task.task_id,
                tool_id=tool_id
            )
            
        import time
        started_at = time.perf_counter()
        
        log.info("ToolExecutor: ENTER — tool_id=%s inputs_keys=%s", tool_id, list(task.inputs.keys()))

        try:
            tool_result = await self._tool_manager.execute_tool(tool_id, task.inputs)
            
            if tool_result.ok:
                result = RuntimeResult(
                    task_id=task.task_id,
                    status=TaskStatus.COMPLETED,
                    routing=routing,
                    output=tool_result.data,
                )
            elif tool_result.error == "MULTIPLE_MATCHES":
                result = RuntimeResult(
                    task_id=task.task_id,
                    status=TaskStatus.PAUSED,
                    routing=routing,
                    pause=ExecutionPause(
                        reason="multiple_matches",
                        metadata={"candidates": tool_result.data.get("candidates", [])},
                    ),
                    error=tool_result.error,
                )
            else:
                result = RuntimeResult(
                    task_id=task.task_id,
                    status=TaskStatus.FAILED,
                    routing=routing,
                    error=tool_result.error or "Tool execution failed",
                )
        except Exception as e:
            result = RuntimeResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                routing=routing,
                error=str(e),
            )
            
        if context and context.trace:
            context.trace.add_event(
                source="runtime",
                event_type="runtime.tool.completed" if result.status == TaskStatus.COMPLETED else "runtime.tool.failed",
                duration_ms=(time.perf_counter() - started_at) * 1000,
                task_id=task.task_id,
            )

        log.info("ToolExecutor: EXIT — status=%s error=%s has_output=%s", result.status, result.error, result.output is not None)
            
        return result
