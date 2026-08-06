import logging
from typing import Dict, List, Optional, Tuple

from app.tools.base import Tool
from app.tools.models import ToolInfo

logger = logging.getLogger(__name__)


class ToolRegistry:
    """In-memory registry for system tools.

    Owns discovery: dynamic registration plus lookup by id, capability,
    category, version and availability.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, Tuple[Tool, ToolInfo]] = {}

    def register(self, tool_id: str, tool: Tool, info: ToolInfo) -> None:
        """Register a tool along with its metadata.

        Duplicate tool ids are rejected: a silent re-registration can shadow a
        working tool with another implementation, so the capability set stays
        deterministic.
        """
        if tool_id in self._tools:
            raise ValueError(f"Tool already registered: {tool_id}")
        self._tools[tool_id] = (tool, info)

    def unregister(self, tool_id: str) -> bool:
        """Remove a previously registered tool (idempotent)."""
        return self._tools.pop(tool_id, None) is not None

    def get_tool(self, tool_id: str) -> Optional[Tool]:
        """Retrieve a tool by its ID."""
        record = self._tools.get(tool_id)
        tool = record[0] if record else None
        logger.info("ToolRegistry: lookup — tool_id=%s found=%s", tool_id, tool is not None)
        if record:
            return record[0]
        return None

    def get_tool_and_info(self, tool_id: str) -> Optional[Tuple[Tool, ToolInfo]]:
        """Retrieve the tool instance and its metadata as a pair."""
        return self._tools.get(tool_id)

    def info_for(self, tool_id: str) -> Optional[ToolInfo]:
        """Return metadata for a single tool, or None when unregistered."""
        record = self._tools.get(tool_id)
        return record[1] if record else None

    def has_tool(self, tool_id: str) -> bool:
        return tool_id in self._tools

    def list_tools(self) -> List[ToolInfo]:
        """List metadata for all registered tools."""
        return [info for _, info in self._tools.values()]

    def list_by_capability(self, capability: str) -> List[ToolInfo]:
        """Legacy alias for find_tools_by_capability."""
        return self.find_tools_by_capability(capability)

    def find_tools_by_capability(self, capability: str) -> List[ToolInfo]:
        """Return tools declaring a capability in deterministic order."""
        capability_l = capability.lower()
        return [
            info for info in self.list_tools()
            if capability_l in {c.lower() for c in info.capabilities}
        ]

    def find_tools_by_category(self, category: str) -> List[ToolInfo]:
        """Return tools belonging to a category in deterministic order."""
        return [
            info for info in self.list_tools()
            if (info.category or "") == category
        ]

    def find_tools_by_version(self, version: str) -> List[ToolInfo]:
        """Return tools declaring a specific version."""
        return [info for info in self.list_tools() if info.version == version]

    def find_available_tools(self) -> List[ToolInfo]:
        """Return tools currently marked available."""
        return [info for info in self.list_tools() if info.available]

    def set_availability(self, tool_id: str, available: bool) -> bool:
        """Mark a tool available/unavailable for discovery."""
        info = self.info_for(tool_id)
        if info is None:
            return False
        info.available = available
        return True

    def validate_dependencies(self, tool_ids: List[str]) -> bool:
        """Validate that a list of tool IDs are all registered.
        
        Useful for validating tool chains before execution.
        """
        for tool_id in tool_ids:
            if tool_id not in self._tools:
                return False
        return True
