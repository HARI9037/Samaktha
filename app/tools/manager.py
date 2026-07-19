from typing import List, Optional

from app.tools.base import Tool
from app.tools.models import ToolInfo
from app.tools.registry import ToolRegistry


class ToolManager:
    """Coordinates tool resolution and access."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def resolve_tool(self, tool_id: str) -> Optional[Tool]:
        """Resolve a requested tool by its ID."""
        return self._registry.get_tool(tool_id)

    def list_tools(self) -> List[ToolInfo]:
        """List all available tools."""
        return self._registry.list_tools()
