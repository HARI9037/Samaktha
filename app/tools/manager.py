from typing import Any, List, Optional

from app.tools.base import Tool, ToolResult
from app.tools.framework.dispatcher import ToolCall, ToolDispatcher
from app.tools.framework.health import ToolHealthMonitor
from app.tools.framework.memory import ToolMemoryStore
from app.tools.framework.models import ToolContext
from app.tools.metrics import ToolMetricsCollector, ToolMetricsSnapshot
from app.tools.models import ToolInfo
from app.tools.registry import ToolRegistry


class ToolManager:
    """Coordinates tool resolution, execution and discovery.

    Execution is delegated to the ToolDispatcher (the framework's
    execution engine); this class preserves the legacy boundary API.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        memory: Optional[ToolMemoryStore] = None,
    ) -> None:
        self._registry = registry
        self._metrics = ToolMetricsCollector()
        self._memory = memory or ToolMemoryStore()
        self._dispatcher = ToolDispatcher(
            resolve=registry.get_tool_and_info,
            health_monitor=ToolHealthMonitor(),
            memory=self._memory,
        )

    def get_metrics(self) -> ToolMetricsSnapshot:
        return self._metrics.get_metrics()

    @property
    def memory(self) -> ToolMemoryStore:
        return self._memory

    @property
    def dispatcher(self) -> ToolDispatcher:
        return self._dispatcher

    async def execute_tool(
        self,
        tool_id: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        """Resolve and execute a tool, recording metrics at this boundary."""
        result = await self._dispatcher.execute(tool_id, arguments)
        self._metrics.record_execution(success=result.ok)
        return result

    async def execute_tool_with_context(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        context: Optional[ToolContext] = None,
        cancel_event: Any = None,
    ) -> ToolResult:
        """Execute a tool with permission-aware context and cancellation."""
        result = await self._dispatcher.execute(
            tool_id, arguments, context=context, cancel_event=cancel_event
        )
        self._metrics.record_execution(success=result.ok)
        return result

    async def execute_many(
        self,
        calls: list[ToolCall],
        context: Optional[ToolContext] = None,
    ) -> list[ToolResult]:
        """Execute several tools concurrently (independent calls)."""
        return await self._dispatcher.execute_many(calls, context=context)

    async def execute_ordered(
        self,
        calls: list[ToolCall],
        dependencies: Optional[dict[int, list[int]]] = None,
        context: Optional[ToolContext] = None,
    ) -> list[ToolResult]:
        """Execute calls respecting a dependency graph between indices."""
        return await self._dispatcher.execute_ordered(calls, dependencies, context)

    def execution_reports(self) -> list[Any]:
        return self._dispatcher.reports()

    def last_execution_report(self) -> Optional[Any]:
        return self._dispatcher.last_report()

    def resolve_tool(self, tool_id: str) -> Optional[Tool]:
        """Resolve a requested tool by its ID."""
        return self._registry.get_tool(tool_id)

    def list_tools(self) -> List[ToolInfo]:
        """List all available tools."""
        return self._registry.list_tools()

    def list_tools_by_capability(self, capability: str) -> List[ToolInfo]:
        """Discover registered tools by declared capability."""
        return self._registry.find_tools_by_capability(capability)

    def find_tools_by_capability(self, capability: str) -> List[ToolInfo]:
        """List all tools declaring a specific capability."""
        return self._registry.find_tools_by_capability(capability)

    def find_tools_by_category(self, category: str) -> List[ToolInfo]:
        """List all tools in a category."""
        return self._registry.find_tools_by_category(category)

    def find_tools_by_version(self, version: str) -> List[ToolInfo]:
        """List all tools declaring a version."""
        return self._registry.find_tools_by_version(version)

    def find_available_tools(self) -> List[ToolInfo]:
        """List tools currently available."""
        return self._registry.find_available_tools()

    def get_tool_info(self, tool_id: str) -> Optional[ToolInfo]:
        """Return metadata for one tool."""
        return self._registry.info_for(tool_id)

    def has_tool(self, tool_id: str) -> bool:
        return self._registry.has_tool(tool_id)

    def set_availability(self, tool_id: str, available: bool) -> bool:
        return self._registry.set_availability(tool_id, available)

    def validate_tool_capabilities(
        self,
        tool_id: str,
        required_capabilities: list[str],
    ) -> bool:
        info = next(
            (item for item in self.list_tools() if item.tool_id == tool_id),
            None,
        )
        return info is not None and set(required_capabilities).issubset(
            set(info.capabilities)
        )
