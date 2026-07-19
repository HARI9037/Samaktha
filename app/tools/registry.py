from typing import Dict, List, Optional, Tuple

from app.tools.base import Tool
from app.tools.models import ToolInfo


class ToolRegistry:
    """In-memory registry for system tools."""

    def __init__(self) -> None:
        self._tools: Dict[str, Tuple[Tool, ToolInfo]] = {}

    def register(self, tool_id: str, tool: Tool, info: ToolInfo) -> None:
        """Register a tool along with its metadata."""
        self._tools[tool_id] = (tool, info)

    def get_tool(self, tool_id: str) -> Optional[Tool]:
        """Retrieve a tool by its ID."""
        record = self._tools.get(tool_id)
        if record:
            return record[0]
        return None

    def list_tools(self) -> List[ToolInfo]:
        """List metadata for all registered tools."""
        return [info for _, info in self._tools.values()]

    def list_by_capability(self, capability: str) -> List[ToolInfo]:
        """Return tools declaring a capability in deterministic order."""
        return [
            info for info in self.list_tools()
            if capability in info.capabilities
        ]
