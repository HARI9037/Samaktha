"""Phase 8.1 — Memory Controller (Facade).

Public API for the entire Memory Controller layer.

Integrates:
    - MemoryWriter           — typed writes
    - MemoryRetriever        — pipeline retrieval
    - MemoryRanker           — multi-signal scoring
    - MemoryConsolidator     — dedup, merge, decay
    - MetadataManager        — metadata enrichment
    - SecurityManager        — integrity, CAP access checks
    - LifecycleManager       — archival, expiry, deletion
    - MemoryCache            — in-memory cache
    - PreferenceResolver     — conflict resolution for preferences

All methods delegate to the existing MemoryManager and stores.
No existing API is modified.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.contracts.memory import MemoryItem
from app.core.contracts.security import SecurityLevel
from app.memory.controller.cache import MemoryCache
from app.memory.controller.consolidator import MemoryConsolidator
from app.memory.controller.lifecycle_manager import LifecycleManager
from app.memory.controller.metadata_manager import update_accessed
from app.memory.controller.preference_resolver import PreferenceResolver
from app.memory.controller.ranker import MemoryRanker
from app.memory.controller.retriever import MemoryRetriever, SemanticEngine
from app.memory.controller.security_manager import SecurityManager
from app.memory.controller.writer import MemoryWriter
from app.memory.documents import DocumentRecord
from app.memory.manager import MemoryManager

log = logging.getLogger(__name__)


class MemoryController:
    """Public facade for the Phase 8 Memory Controller.

    Usage (from CAP, GAMBIT, Runtime, Workflow)::

        controller = MemoryController(memory_manager)

        # Write
        controller.write_conversation("User: ...\\nAssistant: ...")

        # Retrieve
        results = controller.retrieve("user query")

        # Maintain
        controller.run_maintenance()
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        semantic_engine: SemanticEngine | None = None,
        ranker: MemoryRanker | None = None,
        cache: MemoryCache | None = None,
        security: SecurityManager | None = None,
        writer: MemoryWriter | None = None,
        retriever: MemoryRetriever | None = None,
        consolidator: MemoryConsolidator | None = None,
        lifecycle: LifecycleManager | None = None,
        preference_resolver: PreferenceResolver | None = None,
    ) -> None:
        self._memory_manager = memory_manager

        # Build default dependency chain (overridable via injection)
        self._cache = cache or MemoryCache()
        self._security = security or SecurityManager()
        self._ranker = ranker or MemoryRanker()
        self._consolidator = consolidator or MemoryConsolidator(
            memory_manager, self._cache
        )
        self._lifecycle = lifecycle or LifecycleManager(
            memory_manager, self._cache, self._consolidator
        )
        self._writer = writer or MemoryWriter(
            memory_manager, self._cache, self._security
        )
        self._retriever = retriever or MemoryRetriever(
            memory_manager, self._cache, self._ranker, semantic_engine
        )
        self._preference_resolver = preference_resolver or PreferenceResolver(
            memory_manager, self._cache
        )

    # ------------------------------------------------------------------
    # Properties — expose sub-modules for advanced use
    # ------------------------------------------------------------------

    @property
    def memory_manager(self) -> MemoryManager:
        return self._memory_manager

    @property
    def writer(self) -> MemoryWriter:
        return self._writer

    @property
    def retriever(self) -> MemoryRetriever:
        return self._retriever

    @property
    def ranker(self) -> MemoryRanker:
        return self._ranker

    @property
    def consolidator(self) -> MemoryConsolidator:
        return self._consolidator

    @property
    def security(self) -> SecurityManager:
        return self._security

    @property
    def lifecycle(self) -> LifecycleManager:
        return self._lifecycle

    @property
    def cache(self) -> MemoryCache:
        return self._cache

    @property
    def preference_resolver(self) -> PreferenceResolver:
        return self._preference_resolver

    # ------------------------------------------------------------------
    # Typed write methods
    # ------------------------------------------------------------------

    def write_conversation(
        self,
        content: str,
        session_id: str | None = None,
        conversation_id: str | None = None,
        tags: list[str] | None = None,
        importance_kind: str = "conversation",
        security_level: SecurityLevel = SecurityLevel.LOW,
    ) -> MemoryItem:
        decision = self._security.check_write_access("conversation", security_level)
        if not decision.allowed:
            log.warning("MemoryController: write_conversation DENIED by security: %s", decision.reason)
            raise PermissionError(decision.reason)
        item = self._writer.write_conversation(
            content=content,
            session_id=session_id,
            conversation_id=conversation_id,
            tags=tags,
            importance_kind=importance_kind,
            security_level=security_level,
        )
        self._cache.clear_retrievals()
        return item

    def _check_write_access(
        self, memory_type: str, security_level: SecurityLevel
    ) -> None:
        decision = self._security.check_write_access(memory_type, security_level)
        if not decision.allowed:
            log.warning("MemoryController: write_%s DENIED by security: %s", memory_type, decision.reason)
            raise PermissionError(decision.reason)

    def write_document(
        self,
        content: str,
        source_path: str,
        doc_name: str,
        session_id: str | None = None,
        tags: list[str] | None = None,
        importance_kind: str = "tool_output",
        security_level: SecurityLevel = SecurityLevel.LOW,
    ) -> MemoryItem:
        self._check_write_access("document", security_level)
        item = self._writer.write_document(
            content=content,
            source_path=source_path,
            doc_name=doc_name,
            session_id=session_id,
            tags=tags,
            importance_kind=importance_kind,
            security_level=security_level,
        )
        self._cache.clear_retrievals()
        return item

    def write_preference(
        self,
        content: str,
        session_id: str | None = None,
        tags: list[str] | None = None,
        security_level: SecurityLevel = SecurityLevel.LOW,
    ) -> MemoryItem:
        self._check_write_access("preference", security_level)

        # Resolve against existing preferences
        resolved, is_new = self._preference_resolver.resolve(
            content=content,
            session_id=session_id,
            tags=tags,
        )

        if is_new:
            # Store new item
            self._memory_manager.store_memory(resolved)
            self._cache.store_recent_memory(resolved.id, resolved)
            log.debug("MemoryController: stored new preference %s", resolved.id)
        else:
            # Existing item was updated in-place by the resolver
            self._cache.store_recent_memory(resolved.id, resolved)
            log.debug("MemoryController: resolved preference → updated %s", resolved.id)

        self._cache.clear_retrievals()
        return resolved

    def write_workflow(
        self,
        content: str,
        workflow_id: str,
        session_id: str | None = None,
        tags: list[str] | None = None,
        success: bool = True,
        security_level: SecurityLevel = SecurityLevel.LOW,
    ) -> MemoryItem:
        self._check_write_access("workflow", security_level)
        item = self._writer.write_workflow(
            content=content,
            workflow_id=workflow_id,
            session_id=session_id,
            tags=tags,
            success=success,
            security_level=security_level,
        )
        self._cache.clear_retrievals()
        return item

    def write_tool(
        self,
        content: str,
        tool_name: str,
        session_id: str | None = None,
        tags: list[str] | None = None,
        security_level: SecurityLevel = SecurityLevel.LOW,
    ) -> MemoryItem:
        self._check_write_access("tool", security_level)
        item = self._writer.write_tool(
            content=content,
            tool_name=tool_name,
            session_id=session_id,
            tags=tags,
            security_level=security_level,
        )
        self._cache.clear_retrievals()
        return item

    def write_knowledge(
        self,
        content: str,
        source: str = "system",
        tags: list[str] | None = None,
        importance_kind: str = "successful_workflow",
        security_level: SecurityLevel = SecurityLevel.LOW,
    ) -> MemoryItem:
        self._check_write_access("knowledge", security_level)
        item = self._writer.write_knowledge(
            content=content,
            source=source,
            tags=tags,
            importance_kind=importance_kind,
            security_level=security_level,
        )
        self._cache.clear_retrievals()
        return item

    def write_system(
        self,
        content: str,
        tags: list[str] | None = None,
        security_level: SecurityLevel = SecurityLevel.LOW,
    ) -> MemoryItem:
        self._check_write_access("system", security_level)
        item = self._writer.write_system(
            content=content,
            tags=tags,
            security_level=security_level,
        )
        self._cache.clear_retrievals()
        return item

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        top_k: int = 15,
        session_id: str | None = None,
        include_recent: bool = True,
        include_semantic: bool = True,
        include_skills: bool = True,
        include_preferences: bool = True,
        include_documents: bool = True,
    ) -> list[tuple[Any, float]]:
        """Full retrieval pipeline — returns ranked (item, score) pairs."""
        return self._retriever.retrieve(
            query=query,
            top_k=top_k,
            session_id=session_id,
            include_recent=include_recent,
            include_semantic=include_semantic,
            include_skills=include_skills,
            include_preferences=include_preferences,
            include_documents=include_documents,
        )

    def retrieve_recent(self, n: int = 10) -> list[Any]:
        """Quick access to recent context only."""
        return self._retriever.retrieve_recent_only(n=n)

    def retrieve_semantic(self, query: str, top_k: int = 10) -> list[Any]:
        """Quick semantic search only."""
        return self._retriever.retrieve_semantic_only(query=query, top_k=top_k)

    def search_documents(self, query: str = "") -> list[DocumentRecord]:
        """Search DocumentMemoryStore by name, tag, or summary.

        This is the preferred entry point for document-history questions
        (e.g., "What document did I read today?").

        Returns document records sorted by recency.
        """
        return self._memory_manager.search_documents(query)

    # ------------------------------------------------------------------
    # Consolidation
    # ------------------------------------------------------------------

    def find_duplicates(
        self,
        items: list[Any],
        threshold: float = 0.85,
    ) -> list[tuple[Any, Any, float]]:
        return self._consolidator.find_duplicates(items, threshold=threshold)

    def merge_duplicates(self, primary: Any, duplicate: Any) -> Any:
        return self._consolidator.merge_duplicates(primary, duplicate)

    def decay_importance(
        self,
        stale_days: int = 14,
        decay_factor: float = 0.85,
    ) -> int:
        items = self._memory_manager.get_recent_context(n=1000)
        return self._consolidator.decay_importance(
            items, stale_days=stale_days, decay_factor=decay_factor
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def expire_old_memories(self) -> int:
        return self._lifecycle.expire_old_memories()

    def archive_memory(self, item_id: str) -> bool:
        return self._lifecycle.archive_memory(item_id)

    def delete_memory(self, item_id: str) -> bool:
        return self._lifecycle.delete_memory(item_id)

    def delete_by_type(self, memory_type: str) -> int:
        return self._lifecycle.delete_by_type(memory_type)

    def delete_all(self) -> dict[str, int]:
        """Permanently delete every persisted memory and clear all caches.

        Delegates to MemoryManager.delete_all_memories (SQLite rows + in-memory
        stores) and drops the retrieval/memory caches so a fresh hydration on
        restart finds nothing. Returns a count per storage family.
        """
        counts = self._memory_manager.delete_all_memories()
        self._cache.clear_all()
        log.info("MemoryController: delete_all removed %r", counts)
        return counts

    def promote_memory(
        self, item_id: str, new_importance: float | None = None
    ) -> bool:
        return self._lifecycle.promote_memory(item_id, new_importance)

    def run_maintenance(self) -> dict[str, int]:
        """Run full lifecycle maintenance cycle."""
        return self._lifecycle.run_maintenance()

    # ------------------------------------------------------------------
    # Cache operations
    # ------------------------------------------------------------------

    def clear_cache(self) -> None:
        self._cache.clear_all()

    def cache_stats(self) -> dict[str, Any]:
        return {
            "memories": self._cache.memory_count(),
            "documents": self._cache.document_count(),
            "skills": self._cache.skill_count(),
            "hits": self._cache.hit_count,
            "misses": self._cache.miss_count,
            "hit_rate": self._cache.hit_rate,
        }

    # ------------------------------------------------------------------
    # Metadata enrichment
    # ------------------------------------------------------------------

    @staticmethod
    def update_accessed(item: Any) -> None:
        """Bump last_accessed and access_counter on an item's metadata."""
        if hasattr(item, "metadata") and isinstance(item.metadata, dict):
            update_accessed(item.metadata)

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------

    def register_access_rule(
        self, memory_type: str, required_level: SecurityLevel
    ) -> None:
        self._security.register_access_rule(memory_type, required_level)

    def check_read_access(
        self,
        memory_type: str,
        memory_security_level: SecurityLevel = SecurityLevel.LOW,
        user_security_level: SecurityLevel = SecurityLevel.LOW,
    ) -> bool:
        return self._security.check_read_access(
            memory_type, memory_security_level, user_security_level
        ).allowed
