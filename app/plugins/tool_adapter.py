"""Canonical adapter for plugin-contributed tools.

The adapter does not authorize or dispatch work.  It is registered in the
normal ``ToolRegistry`` so invocation remains owned by Runtime's
``ToolExecutor`` and its P7 security boundary.
"""

from __future__ import annotations

from typing import Any

from app.plugins.activity import PluginActivityTracker
from app.tools.base import Tool, ToolResult


class PluginToolAdapter(Tool):
    """Delegate to a plugin tool while tracking its active lifecycle."""

    def __init__(
        self,
        plugin_key: str,
        tool: Tool,
        activity: PluginActivityTracker | None = None,
    ) -> None:
        self.plugin_key = plugin_key
        self._tool = tool
        self._activity = activity

    @property
    def name(self) -> str:
        return self._tool.name

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        if self._activity is not None:
            self._activity.begin(self.name)
        try:
            return await self._tool.run(arguments)
        finally:
            if self._activity is not None:
                self._activity.end(self.name)

    def __getattr__(self, name: str) -> Any:
        """Expose declarative tool metadata without copying its contract."""
        return getattr(self._tool, name)
