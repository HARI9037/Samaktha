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
        return RuntimeResult(
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
        tool = self._tool_manager.resolve_tool(task.action_type)
        if tool is None:
            return RuntimeResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                routing=routing,
                error=f"Tool is not registered: {task.action_type}",
            )

        # Re-map inputs for tool (assuming inputs contains the kwargs)
        try:
            result = await tool.run(task.inputs)
            
            if result.ok:
                return RuntimeResult(
                    task_id=task.task_id,
                    status=TaskStatus.COMPLETED,
                    routing=routing,
                    output=result.data,
                )
            else:
                return RuntimeResult(
                    task_id=task.task_id,
                    status=TaskStatus.FAILED,
                    routing=routing,
                    error=result.error or "Tool execution failed",
                )
        except Exception as e:
            return RuntimeResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                routing=routing,
                error=str(e),
            )
