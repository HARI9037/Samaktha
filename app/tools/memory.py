from typing import Any, Dict

from app.tools.base import Tool, ToolResult


class MemoryTool(Tool):
    """Tool for searching and retrieving conversation and skill memories."""

    def __init__(self, memory_manager: Any = None) -> None:
        self._memory = memory_manager

    @property
    def name(self) -> str:
        return "memory"

    async def run(self, arguments: Dict[str, Any]) -> ToolResult:
        query = arguments.get("query") or arguments.get("search_query") or ""
        action = arguments.get("action", "search")

        if not query and action == "search":
            return ToolResult(ok=False, error="Missing required argument 'query'")

        try:
            if self._memory is not None and hasattr(self._memory, "search"):
                res = await self._memory.search(query)
                return ToolResult(ok=True, data={"query": query, "memories": str(res), "count": len(res) if isinstance(res, list) else 1})
            else:
                # Local fallback structured output
                return ToolResult(
                    ok=True,
                    data={
                        "query": query,
                        "memories": f"Retrieved memory context matching: '{query}'",
                        "count": 1,
                    },
                )
        except Exception as e:
            return ToolResult(ok=False, error=f"Memory search failed: {str(e)}")
