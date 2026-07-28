from typing import Any, List, Optional

from app.tools.base import Tool, ToolResult
from app.tools.metrics import ToolMetricsCollector, ToolMetricsSnapshot
from app.tools.models import ToolInfo
from app.tools.registry import ToolRegistry


class ToolManager:
    """Coordinates tool resolution and access."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self._metrics = ToolMetricsCollector()

    def get_metrics(self) -> ToolMetricsSnapshot:
        return self._metrics.get_metrics()

    async def execute_tool(
        self,
        tool_id: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        """Resolve and execute a tool, recording metrics at this boundary."""
        tool = self._registry.get_tool(tool_id)
        if tool is None:
            self._metrics.record_execution(success=False)
            return ToolResult(ok=False, error=f"Tool not found: {tool_id}")
        try:
            result = await tool.run(arguments)
            self._metrics.record_execution(success=result.ok)
            return result
        except Exception as exc:
            self._metrics.record_execution(success=False)
            return ToolResult(ok=False, error=str(exc))

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
