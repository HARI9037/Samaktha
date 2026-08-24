"""Phase 8 — Memory Retriever.

Pipeline retrieval that combines multiple sources:

    User Query
        ↓
    Recent Retrieval
        ↓
    Semantic Retrieval
        ↓
    Skill Retrieval
        ↓
    Preference Retrieval
        ↓
    Document Retrieval
        ↓
    Merge Results
        ↓
    Ranking
        ↓
    Deduplication
        ↓
    Return Final Context

Each stage delegates to the existing stores (ContextMemoryStore,
SkillMemoryStore, DocumentMemoryStore) or to the cache.

The semantic engine is pluggable — by default uses the existing SemanticIndex
(TF-IDF).  Future engines can be injected without changing public APIs.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Protocol

from app.core.contracts.memory import (
    DEFAULT_LOCAL_PRINCIPAL_ID,
    MemoryAccessContext,
    MemoryScope,
)
from app.memory.controller.cache import MemoryCache
from app.memory.controller.ranker import MemoryRanker
from app.memory.controller.security_manager import SecurityManager
from app.memory.documents import DocumentRecord
from app.memory.manager import MemoryManager

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Document-history query detection patterns
# ---------------------------------------------------------------------------

_DOC_HISTORY_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bwhat\s+doc", re.IGNORECASE),
    re.compile(r"\bwhich\s+doc", re.IGNORECASE),
    re.compile(r"\bdoc.*read\b", re.IGNORECASE),
    re.compile(r"\bdoc.*open\b", re.IGNORECASE),
    re.compile(r"\bdoc.*summariz", re.IGNORECASE),
    re.compile(r"\bpdf.*read\b", re.IGNORECASE),
    re.compile(r"\bpdf.*open\b", re.IGNORECASE),
    re.compile(r"\bfile.*read\b", re.IGNORECASE),
    re.compile(r"\bfile.*summariz", re.IGNORECASE),
    re.compile(r"\bwhat.*read\b.*today", re.IGNORECASE),
    re.compile(r"\bwhat.*read\b.*yesterday", re.IGNORECASE),
    re.compile(r"\blist.*doc", re.IGNORECASE),
    re.compile(r"\bshow.*doc", re.IGNORECASE),
    re.compile(r"\bread.*history", re.IGNORECASE),
    re.compile(r"\brecent.*doc", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Pluggable semantic search interface
# ---------------------------------------------------------------------------


class SemanticEngine(Protocol):
    """Protocol for pluggable semantic search.

    The default implementation wraps the existing SemanticIndex via
    MemoryManager.  Phase 9 can inject sentence-transformers, FAISS,
    ChromaDB, Qdrant, etc. behind this same protocol.
    """

    def search(
        self,
        query: str,
        items: list[Any],
        top_k: int = 10,
    ) -> list[tuple[str, float]]:
        """Return (item_id, score) tuples ranked by semantic similarity."""
        ...


class _DefaultSemanticEngine:
    """Wraps the existing MemoryManager.search_memory as a SemanticEngine."""

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._memory_manager = memory_manager

    def search(
        self,
        query: str,
        items: list[Any] | None = None,
        top_k: int = 10,
    ) -> list[tuple[str, float]]:
        if items is None:
            return []
        from app.memory.semantic_index import SemanticIndex

        index = SemanticIndex()
        for item in items:
            index.index(str(item.id), str(item.content), getattr(item, "metadata", {}))
        return [(item_id, score) for item_id, score, _matched in index.search(query, top_k=top_k)]


class _DocumentContextItem:
    """Wraps a DocumentRecord so it flows through the ranking pipeline as a
    MemoryItem-like object with a ``.content`` attribute."""

    def __init__(self, doc: DocumentRecord) -> None:
        from datetime import timezone
        self.content = f"Document: {doc.name}\nSummary: {doc.summary}"
        self.id = doc.document_id
        self.document_id = doc.document_id
        self.name = doc.name
        self.owner_id = doc.owner_id
        self.scope = doc.scope
        self.session_id = doc.session_id
        self.workspace_id = doc.workspace_id
        self.profile_id = doc.profile_id
        self.privacy_level = getattr(doc, "privacy_level", "low")
        self.retention_policy = "normal"
        self.metadata = {
            "created_at": doc.created_at.isoformat() if hasattr(doc.created_at, "isoformat") else str(doc.created_at),
            "importance": 0.5,
            "memory_type": "document",
            "doc_name": doc.name,
            "source_path": doc.source,
        }


class _PersonalKnowledgeItem:
    """Wraps a personal productivity entity for the ranking pipeline."""

    def __init__(self, entity: Any, entity_type: str) -> None:
        self._entity = entity
        self._entity_type = entity_type
        self._entity_id = getattr(entity, "id", str(id(entity)))
        self.content = str(entity)
        self.id = f"{entity_type}:{self._entity_id}"
        self.owner_id = DEFAULT_LOCAL_PRINCIPAL_ID
        self.scope = MemoryScope.USER
        self.session_id = None
        self.workspace_id = None
        self.profile_id = None
        self.privacy_level = "low"
        self.retention_policy = "normal"
        self.metadata = {
            "entity_type": entity_type,
            "importance": 0.3,
            "memory_type": "personal_knowledge",
        }


# ---------------------------------------------------------------------------
# Retriever
# ---------------------------------------------------------------------------


class MemoryRetriever:
    """Pipeline retriever that combines recent, semantic, skill, preference,
    and document sources into a single ranked, deduplicated result."""

    def __init__(
        self,
        memory_manager: MemoryManager,
        cache: MemoryCache,
        ranker: MemoryRanker,
        semantic_engine: SemanticEngine | None = None,
        top_k_recent: int = 10,
        top_k_semantic: int = 10,
        top_k_skills: int = 5,
        top_k_documents: int = 5,
        security: SecurityManager | None = None,
    ) -> None:
        self._memory_manager = memory_manager
        self._cache = cache
        self._ranker = ranker
        self._semantic = semantic_engine or _DefaultSemanticEngine(memory_manager)
        self._top_k_recent = top_k_recent
        self._top_k_semantic = top_k_semantic
        self._top_k_skills = top_k_skills
        self._top_k_documents = top_k_documents
        self._security = security or SecurityManager()

    # ------------------------------------------------------------------
    # Main retrieval pipeline
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        *,
        include_recent: bool = True,
        include_semantic: bool = True,
        include_skills: bool = True,
        include_preferences: bool = True,
        include_documents: bool = True,
        include_personal_knowledge: bool = True,
        top_k: int = 15,
        session_id: str | None = None,
        access_context: MemoryAccessContext | None = None,
    ) -> list[tuple[Any, float]]:
        """Run the full retrieval pipeline and return ranked results.

        Returns
        -------
        list of (item, score) tuples, sorted by combined score descending.
        """
        if access_context is None:
            raise ValueError("memory retrieval requires MemoryAccessContext")
        # Check cache first. Every access dimension that can change eligibility
        # or security is part of the partition key.
        include_flags = "".join(
            "1" if flag else "0"
            for flag in (
                include_recent,
                include_semantic,
                include_skills,
                include_preferences,
                include_documents,
                include_personal_knowledge,
            )
        )
        cache_key = ":".join((
            access_context.principal_id,
            access_context.session_id or "-",
            access_context.workspace_id or "-",
            access_context.profile_id or "-",
            access_context.security_level.value,
            query,
            str(top_k),
            include_flags,
        ))
        cached = self._cache.get_retrieval(cache_key)
        if cached is not None:
            self._cache.record_hit()
            log.debug("MemoryRetriever: cache hit for %r", cache_key)
            return cached

        self._cache.record_miss()

        # Stage 1: recent memories
        candidates: list[Any] = []
        if include_recent:
            candidates.extend(self._eligible(
                self._retrieve_recent(session_id=session_id), access_context
            ))

        # Stage 2: semantic memories
        semantic_ids: dict[str, float] = {}
        if include_semantic:
            # Eligibility is established before semantic scoring. The default
            # semantic engine receives only this authorized candidate set.
            eligible_items = self._eligible(
                self._memory_manager.get_recent_context(n=100000, allow_private=True),
                access_context,
            )
            sem_items, semantic_ids = self._retrieve_semantic(query, eligible_items)

            # Merge semantic items into candidates (avoid duplicates by id)
            seen_ids = {self._item_id(it) for it in candidates}
            for item in sem_items:
                iid = self._item_id(item)
                if iid not in seen_ids:
                    candidates.append(item)
                    seen_ids.add(iid)

        # Stage 3: skills
        if include_skills:
            # Skill records have no user ownership contract and are treated as
            # SYSTEM scope in P4, so ordinary prompt retrieval does not search
            # or rank them.
            skills = []
            seen_ids = {self._item_id(it) for it in candidates}
            for sk in skills:
                sid = self._item_id(sk)
                if sid not in seen_ids:
                    candidates.append(sk)
                    seen_ids.add(sid)

        # Stage 4: preferences
        if include_preferences:
            prefs = self._eligible(self._retrieve_preferences(), access_context)
            seen_ids = {self._item_id(it) for it in candidates}
            for p in prefs:
                pid = self._item_id(p)
                if pid not in seen_ids:
                    candidates.append(p)
                    seen_ids.add(pid)

        # Stage 5: documents (from cache — document content is stored
        # as memory items via write_document, so recent + semantic already
        # covers them.  This stage adds cached DocumentRecords metadata.)
        if include_documents:
            docs = self._retrieve_documents(query, access_context)
            seen_ids = {self._item_id(it) for it in candidates}
            for d in docs:
                did = self._item_id(d)
                if did not in seen_ids:
                    candidates.append(d)
                    seen_ids.add(did)

        # Stage 6: personal knowledge (reminders, notes, tasks, contacts, calendar)
        if include_personal_knowledge:
            knowledge = (
                self._eligible(
                    self._retrieve_personal_knowledge(query), access_context
                )
                if access_context.principal_id == DEFAULT_LOCAL_PRINCIPAL_ID
                else []
            )
            seen_ids = {self._item_id(it) for it in candidates}
            for k in knowledge:
                kid = self._item_id(k)
                if kid not in seen_ids:
                    candidates.append(k)
                    seen_ids.add(kid)

        # Stage 7: rank
        ranked = self._ranker.rank(candidates, semantic_scores=semantic_ids)

        # Stage 8: deduplicate by id (safety pass)
        deduped = self._deduplicate(ranked)

        result = deduped[:top_k]

        # Cache
        self._cache.store_retrieval(cache_key, result)
        log.debug("MemoryRetriever: retrieved %d items for %r", len(result), query)
        return result

    # ------------------------------------------------------------------
    # Individual retrieval stages
    # ------------------------------------------------------------------

    def _retrieve_recent(
        self, session_id: str | None = None
    ) -> list[Any]:
        """Load recent memories (newest first) from cache or the store."""
        cached = [m for m in self._cache.list_cached_memories() if m is not None]
        if cached:
            # Cache is insertion-ordered (oldest first); take the newest N.
            return list(reversed(cached[-self._top_k_recent:]))

        # Fall back to MemoryManager
        items = self._memory_manager.get_recent_context(n=self._top_k_recent)
        for it in items:
            self._cache.store_recent_memory(it.id, it)
        return items

    def _retrieve_semantic(
        self, query: str, eligible_items: list[Any]
    ) -> tuple[list[Any], dict[str, float]]:
        """Semantic search via the pluggable engine.

        Items are materialized from the cache or the full context store so a
        semantic hit is never dropped merely because it fell outside the
        recent-memory window.
        """
        semantic_results = self._semantic.search(
            query, items=eligible_items, top_k=self._top_k_semantic
        )
        semantic_ids: dict[str, float] = {}
        items: list[Any] = []

        for item_id, score in semantic_results:
            semantic_ids[item_id] = score
            # Try cache first
            item = self._cache.get_recent_memory(item_id)
            if item is None:
                # Load from the full context store (any recency window)
                item = self._memory_manager.get_context_item(item_id)
                if item is not None:
                    self._cache.store_recent_memory(item_id, item)
            if item is not None:
                items.append(item)

        return items, semantic_ids

    def _retrieve_skills(self, query: str) -> list[Any]:
        """Search skills via MemoryManager."""
        try:
            results = self._memory_manager.find_relevant_skills(query)
            return [r.skill for r in results[: self._top_k_skills]]
        except Exception:
            log.warning("MemoryRetriever: skill retrieval failed", exc_info=True)
            return []

    def _retrieve_preferences(self) -> list[Any]:
        """Retrieve preference-flagged items from the full context store.

        Scans all stored items by type (not just the recent-50 window) so a
        preference written before many unrelated conversations is still found.
        """
        prefs = self._memory_manager.get_context_items_by_type(
            "preference", n=50, allow_private=False
        )
        for p in prefs:
            self._cache.store_recent_memory(self._item_id(p), p)
        return prefs

    def _retrieve_documents(
        self,
        query: str,
        access_context: MemoryAccessContext,
    ) -> list[Any]:
        """Retrieve document metadata and convert to MemoryItem-like objects
        for the ranking pipeline."""
        try:
            # Materialize unranked document metadata, establish access, then
            # let the canonical ranker score only the authorized wrappers.
            docs = self._memory_manager.search_documents("")
            if docs:
                wrapped = self._eligible(
                    [_DocumentContextItem(d) for d in docs], access_context
                )
                tokens = [token for token in re.findall(r"[a-z0-9]+", query.lower()) if len(token) > 1]
                matching = [
                    item for item in wrapped
                    if not tokens or any(token in item.content.lower() for token in tokens)
                ]
                if not matching and self._is_document_history_query(query):
                    matching = wrapped
                wrapped = matching[:self._top_k_documents]
                log.debug("MemoryRetriever: document stage — %d results for %r", len(wrapped), query)
                for w in wrapped:
                    log.debug("MemoryRetriever: document item — %s", w.name)
                return wrapped
        except Exception:
            log.warning("MemoryRetriever: document search failed", exc_info=True)
        return []

    def _retrieve_personal_knowledge(self, query: str) -> list[Any]:
        """Retrieve personal productivity entities (reminders, notes, tasks,
        contacts, calendar events) for the ranking pipeline."""
        results: list[Any] = []
        try:
            entity_types = ("reminder", "note", "task", "contact", "calendar_event")
            for entity_type in entity_types:
                items = self._memory_manager.search_personal_knowledge(entity_type, query)
                for item in items:
                    results.append(_PersonalKnowledgeItem(item, entity_type))
        except Exception:
            log.debug("MemoryRetriever: personal knowledge search failed", exc_info=True)
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _item_id(item: Any) -> str:
        if hasattr(item, "id"):
            return str(item.id)
        if hasattr(item, "skill_id"):
            return str(item.skill_id)
        if hasattr(item, "document_id"):
            return str(item.document_id)
        if hasattr(item, "_entity_type") and hasattr(item, "_entity_id"):
            return f"{item._entity_type}:{item._entity_id}"
        return str(id(item))

    @staticmethod
    def _is_document_history_query(query: str) -> bool:
        """Detect queries asking about document read history."""
        return any(p.search(query) for p in _DOC_HISTORY_PATTERNS)

    @staticmethod
    def _deduplicate(
        ranked: list[tuple[Any, float]],
    ) -> list[tuple[Any, float]]:
        seen: set[str] = set()
        result: list[tuple[Any, float]] = []
        for item, score in ranked:
            iid = MemoryRetriever._item_id(item)
            if iid not in seen:
                seen.add(iid)
                result.append((item, score))
        return result

    def retrieve_recent_only(
        self,
        n: int = 10,
        access_context: MemoryAccessContext | None = None,
    ) -> list[Any]:
        """Quick access to recent context without the full pipeline."""
        if access_context is None:
            raise ValueError("memory retrieval requires MemoryAccessContext")
        return self._eligible(
            self._memory_manager.get_recent_context(n=100000, allow_private=True),
            access_context,
        )[:n]

    def retrieve_semantic_only(
        self, query: str, top_k: int = 10,
        access_context: MemoryAccessContext | None = None,
    ) -> list[Any]:
        """Quick semantic search without the full pipeline."""
        if access_context is None:
            raise ValueError("memory retrieval requires MemoryAccessContext")
        eligible = self._eligible(
            self._memory_manager.get_recent_context(n=100000, allow_private=True),
            access_context,
        )
        results = self._semantic.search(query, items=eligible, top_k=top_k)
        items = []
        for item_id, _ in results:
            item = self._cache.get_recent_memory(item_id)
            if item is None:
                item = self._memory_manager.get_context_item(item_id)
            if item is not None:
                items.append(item)
        return items
    def _eligible(
        self,
        items: list[Any],
        access_context: MemoryAccessContext,
    ) -> list[Any]:
        """Ownership then SecurityManager then retention, before ranking."""

        result: list[Any] = []
        for item in items:
            if item is None or not self._security.is_in_scope(item, access_context):
                continue
            decision = self._security.can_read_item(item, access_context)
            if not decision.allowed:
                continue
            if getattr(item, "retention_policy", "normal") == "private":
                continue
            result.append(item)
        return result
