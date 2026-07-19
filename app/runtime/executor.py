from __future__ import annotations

from typing import Any, Protocol

from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeResult, RuntimeTask
from app.core.contracts.planning import TaskStatus


class Executor(Protocol):
    """Runtime-local interface for task executors."""

    async def execute(
        self,
        context: RuntimeContext,
        task: RuntimeTask,
        routing: RoutingDecision,
    ) -> RuntimeResult:
        raise NotImplementedError


class ProviderManagerLike(Protocol):
    """Provider manager shape required by Runtime."""

    def resolve_provider(self, provider_id: str) -> ProviderLike | None:
        raise NotImplementedError

    async def execute_provider(
        self,
        provider_id: str,
        payload: dict[str, Any],
        model_id: str | None = None,
        required_capabilities: list[str] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError


class ProviderLike(Protocol):
    """Provider shape required by Runtime without importing provider modules."""

    @property
    def name(self) -> str:
        raise NotImplementedError

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
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
        if context and context.trace:
            context.trace.add_event(
                source="runtime",
                event_type="runtime.provider.started",
                task_id=task.task_id,
                provider_id=routing.provider_id,
                model_id=routing.model_id
            )
            
        import time
        started_at = time.perf_counter()
        
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
        
        if context and context.trace:
            context.trace.add_event(
                source="runtime",
                event_type="runtime.provider.completed" if status == TaskStatus.COMPLETED else "runtime.provider.failed",
                duration_ms=(time.perf_counter() - started_at) * 1000,
                task_id=task.task_id,
            )
            
        return result


class ToolLike(Protocol):
    """Tool shape required by Runtime without importing tool modules."""

    @property
    def name(self) -> str:
        raise NotImplementedError

    async def run(self, arguments: dict[str, Any]) -> Any:
        raise NotImplementedError


class ToolManagerLike(Protocol):
    """Tool manager shape required by Runtime."""

    def resolve_tool(self, tool_id: str) -> ToolLike | None:
        raise NotImplementedError


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
        if context and context.trace:
            context.trace.add_event(
                source="runtime",
                event_type="runtime.tool.started",
                task_id=task.task_id,
                tool_id=task.action_type
            )
            
        import time
        started_at = time.perf_counter()
        
        tool = self._tool_manager.resolve_tool(task.action_type)
        if tool is None:
            if context and context.trace:
                context.trace.add_event(
                    source="runtime",
                    event_type="runtime.tool.failed",
                    duration_ms=(time.perf_counter() - started_at) * 1000,
                    task_id=task.task_id,
                    error=f"Tool is not registered: {task.action_type}"
                )
            return RuntimeResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                routing=routing,
                error=f"Tool is not registered: {task.action_type}",
            )

        # Re-map inputs for tool (assuming inputs contains the kwargs)
        try:
            tool_result = await tool.run(task.inputs)
            
            if tool_result.ok:
                result = RuntimeResult(
                    task_id=task.task_id,
                    status=TaskStatus.COMPLETED,
                    routing=routing,
                    output=tool_result.data,
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
            
        return result
