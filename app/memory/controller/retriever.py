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

from app.memory.controller.cache import MemoryCache
from app.memory.controller.ranker import MemoryRanker
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
        results = self._memory_manager.search_memory(query, top_k=top_k)
        return [(r.item.id, r.score) for r in results]


class _DocumentContextItem:
    """Wraps a DocumentRecord so it flows through the ranking pipeline as a
    MemoryItem-like object with a ``.content`` attribute."""

    def __init__(self, doc: DocumentRecord) -> None:
        from datetime import timezone
        self.content = f"Document: {doc.name}\nSummary: {doc.summary}"
        self.id = doc.document_id
        self.document_id = doc.document_id
        self.name = doc.name
        self.metadata = {
            "created_at": doc.created_at.isoformat() if hasattr(doc.created_at, "isoformat") else str(doc.created_at),
            "importance": 0.5,
            "memory_type": "document",
            "doc_name": doc.name,
            "source_path": doc.source,
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
    ) -> None:
        self._memory_manager = memory_manager
        self._cache = cache
        self._ranker = ranker
        self._semantic = semantic_engine or _DefaultSemanticEngine(memory_manager)
        self._top_k_recent = top_k_recent
        self._top_k_semantic = top_k_semantic
        self._top_k_skills = top_k_skills
        self._top_k_documents = top_k_documents

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
        top_k: int = 15,
        session_id: str | None = None,
    ) -> list[tuple[Any, float]]:
        """Run the full retrieval pipeline and return ranked results.

        Returns
        -------
        list of (item, score) tuples, sorted by combined score descending.
        """
        # Check cache first
        cache_key = f"{query}:{top_k}:{session_id}"
        cached = self._cache.get_retrieval(cache_key)
        if cached is not None:
            self._cache.record_hit()
            log.debug("MemoryRetriever: cache hit for %r", cache_key)
            return cached

        self._cache.record_miss()

        # Stage 1: recent memories
        candidates: list[Any] = []
        if include_recent:
            candidates.extend(self._retrieve_recent(session_id=session_id))

        # Stage 2: semantic memories
        semantic_ids: dict[str, float] = {}
        if include_semantic:
            sem_items, semantic_ids = self._retrieve_semantic(query)

            # Merge semantic items into candidates (avoid duplicates by id)
            seen_ids = {self._item_id(it) for it in candidates}
            for item in sem_items:
                iid = self._item_id(item)
                if iid not in seen_ids:
                    candidates.append(item)
                    seen_ids.add(iid)

        # Stage 3: skills
        if include_skills:
            skills = self._retrieve_skills(query)
            seen_ids = {self._item_id(it) for it in candidates}
            for sk in skills:
                sid = self._item_id(sk)
                if sid not in seen_ids:
                    candidates.append(sk)
                    seen_ids.add(sid)

        # Stage 4: preferences
        if include_preferences:
            prefs = self._retrieve_preferences()
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
            docs = self._retrieve_documents(query)
            seen_ids = {self._item_id(it) for it in candidates}
            for d in docs:
                did = self._item_id(d)
                if did not in seen_ids:
                    candidates.append(d)
                    seen_ids.add(did)

        # Stage 6: rank
        ranked = self._ranker.rank(candidates, semantic_scores=semantic_ids)

        # Stage 7: deduplicate by id (safety pass)
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
        """Load recent memories from cache (which mirrors ContextMemoryStore)."""
        cached = self._cache.list_cached_memories()
        if cached:
            return cached[: self._top_k_recent]

        # Fall back to MemoryManager
        items = self._memory_manager.get_recent_context(n=self._top_k_recent)
        for it in items:
            self._cache.store_recent_memory(it.id, it)
        return items

    def _retrieve_semantic(
        self, query: str
    ) -> tuple[list[Any], dict[str, float]]:
        """Semantic search via the pluggable engine."""
        semantic_results = self._semantic.search(query, top_k=self._top_k_semantic)
        semantic_ids: dict[str, float] = {}
        items: list[Any] = []

        for item_id, score in semantic_results:
            semantic_ids[item_id] = score
            # Try cache first
            item = self._cache.get_recent_memory(item_id)
            if item is None:
                # Load from MemoryManager (searches for it by semantic match)
                raw = self._memory_manager.get_recent_context(n=100)
                for r in raw:
                    if r.id == item_id:
                        item = r
                        self._cache.store_recent_memory(r.id, r)
                        break
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
        """Retrieve preference-flagged items from recent memories."""
        all_items = self._cache.list_cached_memories()
        if not all_items:
            all_items = self._memory_manager.get_recent_context(n=50)
        prefs = []
        for item in all_items:
            meta = getattr(item, "metadata", {})
            if isinstance(meta, dict) and meta.get("memory_type") == "preference":
                prefs.append(item)
        return prefs

    def _retrieve_documents(self, query: str) -> list[Any]:
        """Retrieve document metadata and convert to MemoryItem-like objects
        for the ranking pipeline."""
        try:
            docs = self._memory_manager.search_documents(query)
            if docs:
                wrapped = [_DocumentContextItem(d) for d in docs[:self._top_k_documents]]
                log.debug("MemoryRetriever: document stage — %d results for %r", len(wrapped), query)
                for w in wrapped:
                    log.debug("MemoryRetriever: document item — %s", w.name)
                return wrapped
        except Exception:
            log.warning("MemoryRetriever: document search failed", exc_info=True)
        return []

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

    def retrieve_recent_only(self, n: int = 10) -> list[Any]:
        """Quick access to recent context without the full pipeline."""
        return self._memory_manager.get_recent_context(n=n)

    def retrieve_semantic_only(
        self, query: str, top_k: int = 10
    ) -> list[Any]:
        """Quick semantic search without the full pipeline."""
        results = self._semantic.search(query, top_k=top_k)
        items = []
        for item_id, _ in results:
            item = self._cache.get_recent_memory(item_id)
            if item is not None:
                items.append(item)
        return items
