from typing import Any, Dict

from app.tools.base import Tool, ToolResult


class MemoryTool(Tool):
    """Deterministic tool over the local memory stores.

    Supported actions (no LLM reasoning, no heuristics):
        search        — search conversation/skill memories by query
        delete        — delete one memory (by item_id, or by content match)
        delete_type   — delete all memories of a given type
        delete_all    — delete every persisted memory and every session
        delete_session— delete one session (folder + index + exports)
    """

    def __init__(
        self,
        memory_manager: Any = None,
        memory_controller: Any = None,
        session_manager: Any = None,
    ) -> None:
        self._memory = memory_manager
        self._controller = memory_controller
        self._session_manager = session_manager

    @property
    def name(self) -> str:
        return "memory"

    async def run(self, arguments: Dict[str, Any]) -> ToolResult:
        query = arguments.get("query") or arguments.get("search_query") or ""
        action = arguments.get("action", "search")

        try:
            if action == "search":
                return await self._search(query)
            if action == "delete":
                return await self._delete(arguments)
            if action == "delete_type":
                return await self._delete_type(arguments)
            if action == "delete_all":
                return await self._delete_all()
            if action == "delete_session":
                return await self._delete_session(arguments)
            return ToolResult(ok=False, error=f"Unsupported memory action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=f"Memory {action} failed: {str(e)}")

    async def _search(self, query: str) -> ToolResult:
        if not query:
            return ToolResult(ok=False, error="Missing required argument 'query'")
        if self._memory is not None and hasattr(self._memory, "search"):
            res = await self._memory.search(query)
            if not isinstance(res, list):
                return ToolResult(
                    ok=False,
                    error="Memory search backend returned an invalid result",
                )
            return ToolResult(
                ok=True,
                data={
                    "query": query,
                    "memories": [str(item) for item in res],
                    "count": len(res),
                },
            )
        return ToolResult(ok=False, error="Memory search backend unavailable")

    async def _delete(self, arguments: Dict[str, Any]) -> ToolResult:
        item_id = arguments.get("item_id") or ""
        memory_type = arguments.get("memory_type", "")
        query = (arguments.get("query") or arguments.get("search_query") or "").strip()

        if item_id:
            deleted = self._delete_by_id(item_id)
            if not deleted:
                return ToolResult(ok=False, error=f"Memory not found: {item_id}")
            return ToolResult(ok=True, data={"action": "delete", "deleted": deleted, "count": 1})

        if not query:
            return ToolResult(ok=False, error="Missing required argument 'item_id' or 'query'")

        matches = self._find_matching_items(query, memory_type)
        deleted = 0
        for item in matches:
            if self._delete_by_id(getattr(item, "id", "")):
                deleted += 1
        if deleted == 0:
            return ToolResult(ok=False, error=f"No matching memories found to delete for: {query}")
        return ToolResult(
            ok=True,
            data={"action": "delete", "query": query, "deleted": deleted, "count": deleted},
        )

    async def _delete_type(self, arguments: Dict[str, Any]) -> ToolResult:
        memory_type = (arguments.get("memory_type") or "").strip()
        if not memory_type:
            return ToolResult(ok=False, error="Missing required argument 'memory_type'")
        if self._controller is not None and hasattr(self._controller, "delete_by_type"):
            count = self._controller.delete_by_type(memory_type)
            if count == 0:
                return ToolResult(ok=False, error=f"No memories of type '{memory_type}' to delete")
            return ToolResult(ok=True, data={"action": "delete_type", "memory_type": memory_type, "deleted": count, "count": count})
        if self._memory is not None and hasattr(self._memory, "delete_memory_by_type"):
            count = self._memory.delete_memory_by_type(memory_type)
            if count == 0:
                return ToolResult(ok=False, error=f"No memories of type '{memory_type}' to delete")
            return ToolResult(ok=True, data={"action": "delete_type", "memory_type": memory_type, "deleted": count, "count": count})
        return ToolResult(ok=False, error="No memory deletion backend available")

    async def _delete_all(self) -> ToolResult:
        counts: dict[str, Any] = {"mem": 0, "doc": 0, "skill": 0}
        if self._controller is not None and hasattr(self._controller, "delete_all"):
            counts = self._controller.delete_all()
        elif self._memory is not None and hasattr(self._memory, "delete_all_memories"):
            counts = self._memory.delete_all_memories()
        sessions_deleted = 0
        if self._session_manager is not None and hasattr(self._session_manager, "delete_everything"):
            try:
                self._session_manager.delete_everything()
                sessions_deleted = 1
            except Exception:
                sessions_deleted = 0
        memory_deleted = sum(counts.values()) if isinstance(counts, dict) else 0
        if memory_deleted == 0 and sessions_deleted == 0:
            return ToolResult(ok=False, error="Nothing was deleted: no memories or sessions found")
        return ToolResult(
            ok=True,
            data={"action": "delete_all", "memories": counts, "sessions": sessions_deleted},
        )

    async def _delete_session(self, arguments: Dict[str, Any]) -> ToolResult:
        session_id = (arguments.get("session_id") or "").strip()
        if not session_id:
            return ToolResult(ok=False, error="Missing required argument 'session_id'")
        if self._session_manager is None or not hasattr(self._session_manager, "delete_session"):
            return ToolResult(ok=False, error="Session deletion backend unavailable")
        removed = self._session_manager.delete_session(session_id)
        if not removed:
            return ToolResult(ok=False, error=f"Session not found: {session_id}")
        return ToolResult(ok=True, data={"action": "delete_session", "session_id": session_id, "deleted": True})

    # ------------------------------------------------------------------
    # Helpers (deterministic, local)
    # ------------------------------------------------------------------

    def _delete_by_id(self, item_id: str) -> bool:
        if not item_id:
            return False
        if self._controller is not None and hasattr(self._controller, "delete_memory"):
            return bool(self._controller.delete_memory(item_id))
        if self._memory is not None and hasattr(self._memory, "delete_memory"):
            if not self._memory_has(item_id):
                return False
            self._memory.delete_memory(item_id)
            return True
        return False

    def _memory_has(self, item_id: str) -> bool:
        store = getattr(self._memory, "_context_store", None)
        if store is not None and hasattr(store, "get_recent_context"):
            items = store.get_recent_context(n=1000, allow_private=True)
        elif self._memory is not None and hasattr(self._memory, "get_recent_context"):
            items = self._memory.get_recent_context(n=1000, allow_private=True)
        else:
            return False
        return any(getattr(item, "id", None) == item_id for item in items)

    def _find_matching_items(self, query: str, memory_type: str = "") -> list[Any]:
        needle = query.lower()
        items: list[Any] = []
        store = getattr(self._memory, "_context_store", None)
        if store is not None and hasattr(store, "get_recent_context"):
            items = store.get_recent_context(n=1000, allow_private=True)
        elif self._memory is not None and hasattr(self._memory, "get_recent_context"):
            items = self._memory.get_recent_context(n=1000)
        elif self._controller is not None and hasattr(self._controller, "retrieve_recent"):
            items = self._controller.retrieve_recent(n=1000)

        matches = []
        for item in items:
            meta = getattr(item, "metadata", None)
            if not isinstance(meta, dict):
                meta = {}
            if memory_type and meta.get("memory_type") != memory_type:
                continue
            content = str(getattr(item, "content", "") or "").lower()
            tags = " ".join(str(t) for t in meta.get("tags", [])).lower()
            if needle and (needle in content or needle in tags):
                matches.append(item)
        return matches
