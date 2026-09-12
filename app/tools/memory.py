import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict

from app.tools.base import Tool, ToolResult
from app.core.contracts.memory import (
    MemoryAccessContext,
    MemoryEvidenceRecord,
    MemoryRecallIntent,
    MemorySearchEvidence,
    MemoryScope,
    SessionRecallEvidence,
    SessionRecallMessage,
)


log = logging.getLogger(__name__)


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
        access = MemoryAccessContext.model_validate(
            arguments.get("_memory_access_context")
            or MemoryAccessContext.local_default().model_dump()
        )

        try:
            if action == "search":
                return await self._search(query, access, arguments)
            if action == "retrieve":
                return await self._retrieve(arguments, access)
            if action == "last_session":
                return await self._last_session(arguments, access)
            if action == "delete":
                return await self._delete(arguments, access)
            if action == "delete_type":
                return await self._delete_type(arguments, access)
            if action == "delete_all":
                return await self._delete_all(access)
            if action == "delete_session":
                return await self._delete_session(arguments, access)
            return ToolResult(ok=False, error=f"Unsupported memory action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=f"Memory {action} failed: {str(e)}")

    async def _search(
        self,
        query: str,
        access: MemoryAccessContext,
        arguments: dict[str, Any],
    ) -> ToolResult:
        query = self._normalize_search_query(query)
        if self._controller is not None:
            limit = int(arguments.get("limit", 15))
            if query:
                res = self._controller.retrieve(
                    query,
                    top_k=limit,
                    access_context=access,
                )
                items = [item for item, _score in res]
            else:
                # An explicit unqualified memory search means "show the
                # visible durable records", not a semantic search for the
                # command words themselves.
                items = self._controller.retrieve_recent(
                    n=limit, access_context=access
                )
                res = items
            recall_intent = self._recall_intent(arguments)
            memory_type = {
                MemoryRecallIntent.PREFERENCE_RECALL: "preference",
                MemoryRecallIntent.WORKFLOW_RECALL: "workflow",
            }.get(recall_intent)
            if memory_type:
                items = [
                    item for item in items
                    if (getattr(item, "metadata", {}) or {}).get("memory_type")
                    == memory_type
                ]
            items = [item for item in items if self._is_source_record(item)]
            evidence = MemorySearchEvidence(
                intent=recall_intent,
                query=query,
                principal_id=access.principal_id,
                session_id=access.session_id,
                workspace_id=access.workspace_id,
                profile_id=access.profile_id,
                records=[self._evidence_record(item) for item in items],
            )
            serialized = [record.content for record in evidence.records]
        elif self._memory is not None and hasattr(self._memory, "search"):
            # Legacy/test adapter only. Production composition always injects
            # MemoryController and uses the access-controlled branch above.
            res = await self._memory.search(query)
            serialized = [str(item) for item in res] if isinstance(res, list) else []
            evidence = None
        else:
            return ToolResult(ok=False, error="Memory search backend unavailable")
        if not isinstance(res, list):
            return ToolResult(
                ok=False,
                error="Memory search backend returned an invalid result",
            )
        count = evidence.record_count if evidence is not None else len(res)
        log.info(
            "MemoryTool retrieval intent_type=%s scope_type=%s "
            "session_lookup_performed=false memory_search_performed=true "
            "record_count=%d session_count=0",
            self._recall_intent(arguments).value,
            self._scope_type(access),
            count,
        )
        return ToolResult(
            ok=True,
            data={
                "query": query,
                "memories": serialized,
                "count": count,
                **(
                    {"memory_evidence": evidence.model_dump(mode="json")}
                    if evidence is not None
                    else {}
                ),
            },
        )

    async def _retrieve(
        self,
        arguments: dict[str, Any],
        access: MemoryAccessContext,
    ) -> ToolResult:
        """Re-read exact prior result IDs inside the current access scope."""

        ids = [str(value) for value in arguments.get("item_ids", []) if value]
        if not ids or self._controller is None:
            evidence = MemorySearchEvidence(
                intent=self._recall_intent(arguments),
                query=str(arguments.get("query") or ""),
                principal_id=access.principal_id,
                session_id=access.session_id,
                workspace_id=access.workspace_id,
                profile_id=access.profile_id,
            )
        else:
            eligible = self._controller.retrieve_recent(
                n=100_000, access_context=access
            )
            eligible = [item for item in eligible if self._is_source_record(item)]
            by_id = {str(getattr(item, "id", "")): item for item in eligible}
            evidence = MemorySearchEvidence(
                intent=self._recall_intent(arguments),
                query=str(arguments.get("query") or ""),
                principal_id=access.principal_id,
                session_id=access.session_id,
                workspace_id=access.workspace_id,
                profile_id=access.profile_id,
                records=[
                    self._evidence_record(by_id[item_id])
                    for item_id in ids
                    if item_id in by_id
                ],
            )
        log.info(
            "MemoryTool retrieval intent_type=%s scope_type=%s "
            "session_lookup_performed=false memory_search_performed=true "
            "record_count=%d session_count=0",
            evidence.intent.value,
            self._scope_type(access),
            evidence.record_count,
        )
        return ToolResult(
            ok=True,
            data={
                "query": evidence.query,
                "memories": [record.content for record in evidence.records],
                "count": evidence.record_count,
                "memory_evidence": evidence.model_dump(mode="json"),
            },
        )

    async def _last_session(
        self,
        arguments: dict[str, Any],
        access: MemoryAccessContext,
    ) -> ToolResult:
        intent = self._recall_intent(arguments)
        previous = None
        if self._session_manager is not None:
            previous = self._session_manager.previous_session(
                current_session_id=access.session_id,
                principal_id=access.principal_id,
                workspace_id=access.workspace_id,
                profile_id=access.profile_id,
            )
        messages: list[SessionRecallMessage] = []
        if previous is not None:
            archived = self._session_manager.load_archived_history(
                previous.session_id
            )
            history = sorted(
                [*archived, *previous.memory.history],
                key=lambda entry: (entry.turn_number, entry.timestamp, entry.id),
            )
            messages = [
                SessionRecallMessage(
                    message_id=entry.id,
                    role=entry.role,
                    content=entry.content,
                    created_at=self._datetime(entry.timestamp),
                    turn_number=entry.turn_number,
                    provenance=entry.provenance,
                )
                for entry in history
            ]
        evidence = SessionRecallEvidence(
            intent=intent,
            principal_id=access.principal_id,
            current_session_id=access.session_id,
            session_id=previous.session_id if previous is not None else None,
            workspace_id=access.workspace_id,
            profile_id=access.profile_id,
            created_at=(
                self._datetime(previous.metadata.created_at)
                if previous is not None else None
            ),
            updated_at=(
                self._datetime(previous.metadata.updated_at)
                if previous is not None else None
            ),
            stored_message_count=len(messages),
            messages=messages,
            partial=(
                previous is not None
                and previous.metadata.message_count > len(messages)
            ),
        )
        log.info(
            "MemoryTool retrieval intent_type=%s scope_type=%s "
            "session_lookup_performed=true memory_search_performed=false "
            "record_count=%d session_count=%d",
            intent.value,
            self._scope_type(access),
            len(messages),
            evidence.session_count,
        )
        return ToolResult(
            ok=True,
            data={
                "count": len(messages),
                "session_count": evidence.session_count,
                "memory_evidence": evidence.model_dump(mode="json"),
            },
        )

    @staticmethod
    def _recall_intent(arguments: dict[str, Any]) -> MemoryRecallIntent:
        try:
            return MemoryRecallIntent(
                arguments.get("memory_intent")
                or MemoryRecallIntent.MEMORY_SEARCH
            )
        except ValueError:
            return MemoryRecallIntent.MEMORY_SEARCH

    @staticmethod
    def _normalize_search_query(query: str) -> str:
        """Remove only explicit memory-command framing from a search query."""

        normalized = " ".join(str(query or "").strip().split())
        patterns = (
            r"^(?:please\s+)?search\s+(?:through\s+)?(?:your|my|the)?\s*memories?\s*(?:for|about)?\s*",
            r"^(?:please\s+)?(?:show|list)\s+(?:me\s+)?(?:everything|all)(?:\s+that)?\s+(?:you\s+)?(?:have\s+)?(?:saved|stored|remembered)?\s*",
        )
        for pattern in patterns:
            candidate = re.sub(pattern, "", normalized, count=1, flags=re.IGNORECASE)
            if candidate != normalized:
                return candidate.strip(" .?!,:;\t")
        return normalized

    @staticmethod
    def _datetime(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    @classmethod
    def _evidence_record(cls, item: Any) -> MemoryEvidenceRecord:
        metadata = getattr(item, "metadata", {}) or {}
        try:
            scope = MemoryScope(getattr(item, "scope", MemoryScope.USER))
        except (TypeError, ValueError):
            scope = MemoryScope.USER
        importance = metadata.get("importance")
        return MemoryEvidenceRecord(
            memory_id=str(getattr(item, "id", "")),
            memory_type=str(metadata.get("memory_type") or "context"),
            principal_id=str(getattr(item, "owner_id", "")),
            scope=scope,
            content=str(getattr(item, "content", "")),
            session_id=getattr(item, "session_id", None),
            workspace_id=getattr(item, "workspace_id", None),
            profile_id=getattr(item, "profile_id", None),
            importance=(float(importance) if importance is not None else None),
            created_at=cls._datetime(
                getattr(item, "created_at", None) or metadata.get("created_at")
            ),
            updated_at=cls._datetime(
                getattr(item, "updated_at", None) or metadata.get("updated_at")
            ),
            provenance=(
                str(metadata.get("provenance") or metadata.get("source"))
                if metadata.get("provenance") or metadata.get("source")
                else None
            ),
            source_authority=(
                str(metadata.get("source_authority"))
                if metadata.get("source_authority")
                else None
            ),
        )

    @staticmethod
    def _is_source_record(item: Any) -> bool:
        """Exclude answers derived from prior retrieval from source evidence."""

        metadata = getattr(item, "metadata", {}) or {}
        return not (
            metadata.get("provenance") == "generated_summary"
            or metadata.get("source_authority") == "derived_from_memory_evidence"
        )

    @staticmethod
    def _scope_type(access: MemoryAccessContext) -> str:
        if access.workspace_id:
            return "principal_workspace"
        if access.profile_id:
            return "principal_profile"
        return "principal_session"

    async def _delete(
        self, arguments: Dict[str, Any], access: MemoryAccessContext
    ) -> ToolResult:
        item_id = arguments.get("item_id") or ""
        memory_type = arguments.get("memory_type", "")
        query = (arguments.get("query") or arguments.get("search_query") or "").strip()

        if item_id:
            deleted = self._delete_by_id(item_id, access)
            if not deleted:
                return ToolResult(ok=False, error=f"Memory not found: {item_id}")
            return ToolResult(ok=True, data={"action": "delete", "deleted": deleted, "count": 1})

        if not query:
            return ToolResult(ok=False, error="Missing required argument 'item_id' or 'query'")

        matches = self._find_matching_items(query, memory_type, access)
        deleted = 0
        for item in matches:
            if self._delete_by_id(getattr(item, "id", ""), access):
                deleted += 1
        if deleted == 0:
            return ToolResult(ok=False, error=f"No matching memories found to delete for: {query}")
        return ToolResult(
            ok=True,
            data={"action": "delete", "query": query, "deleted": deleted, "count": deleted},
        )

    async def _delete_type(
        self, arguments: Dict[str, Any], access: MemoryAccessContext
    ) -> ToolResult:
        memory_type = (arguments.get("memory_type") or "").strip()
        if not memory_type:
            return ToolResult(ok=False, error="Missing required argument 'memory_type'")
        if self._controller is not None:
            count = sum(
                1
                for item in self._controller.retrieve_recent(
                    n=100000, access_context=access
                )
                if (item.metadata or {}).get("memory_type") == memory_type
                and self._controller.delete_memory(
                    item.id, access_context=access
                )
            )
            if count == 0:
                return ToolResult(ok=False, error=f"No memories of type '{memory_type}' to delete")
            return ToolResult(ok=True, data={"action": "delete_type", "memory_type": memory_type, "deleted": count, "count": count})
        if self._memory is not None and hasattr(self._memory, "delete_memory_by_type"):
            count = self._memory.delete_memory_by_type(memory_type)
            if count == 0:
                return ToolResult(ok=False, error=f"No memories of type '{memory_type}' to delete")
            return ToolResult(ok=True, data={"action": "delete_type", "memory_type": memory_type, "deleted": count, "count": count})
        return ToolResult(ok=False, error="No memory deletion backend available")

    async def _delete_all(self, access: MemoryAccessContext) -> ToolResult:
        counts: dict[str, Any] = {"mem": 0, "doc": 0, "skill": 0}
        if self._controller is not None:
            deleted = sum(
                1
                for item in self._controller.retrieve_recent(
                    n=100000, access_context=access
                )
                if self._controller.delete_memory(item.id, access_context=access)
            )
            counts = {"mem": deleted, "doc": 0, "skill": 0}
        elif self._memory is not None and hasattr(self._memory, "delete_all_memories"):
            counts = self._memory.delete_all_memories()
        sessions_deleted = 0
        if self._session_manager is not None and hasattr(self._session_manager, "delete_everything"):
            try:
                sessions_deleted = sum(
                    1 for meta in self._session_manager.list_sessions(
                        principal_id=access.principal_id
                    )
                    and self._session_manager.delete_session(
                        meta.session_id, principal_id=access.principal_id
                    )
                )
            except Exception:
                sessions_deleted = 0
        memory_deleted = sum(counts.values()) if isinstance(counts, dict) else 0
        if memory_deleted == 0 and sessions_deleted == 0:
            return ToolResult(ok=False, error="Nothing was deleted: no memories or sessions found")
        return ToolResult(
            ok=True,
            data={"action": "delete_all", "memories": counts, "sessions": sessions_deleted},
        )

    async def _delete_session(
        self, arguments: Dict[str, Any], access: MemoryAccessContext
    ) -> ToolResult:
        session_id = (arguments.get("session_id") or "").strip()
        if not session_id:
            return ToolResult(ok=False, error="Missing required argument 'session_id'")
        if self._session_manager is None or not hasattr(self._session_manager, "delete_session"):
            return ToolResult(ok=False, error="Session deletion backend unavailable")
        removed = self._session_manager.delete_session(
            session_id, principal_id=access.principal_id
        )
        if not removed:
            return ToolResult(ok=False, error=f"Session not found: {session_id}")
        return ToolResult(ok=True, data={"action": "delete_session", "session_id": session_id, "deleted": True})

    # ------------------------------------------------------------------
    # Helpers (deterministic, local)
    # ------------------------------------------------------------------

    def _delete_by_id(
        self, item_id: str, access: MemoryAccessContext
    ) -> bool:
        if not item_id:
            return False
        if self._controller is not None and hasattr(self._controller, "delete_memory"):
            return bool(self._controller.delete_memory(
                item_id, access_context=access
            ))
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

    def _find_matching_items(
        self, query: str, memory_type: str = "",
        access: MemoryAccessContext | None = None,
    ) -> list[Any]:
        needle = query.lower()
        items: list[Any] = []
        if self._controller is not None:
            items = self._controller.retrieve_recent(
                n=1000,
                access_context=access or MemoryAccessContext.local_default(),
            )

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
