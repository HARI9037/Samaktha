"""Phase 4.5 — Context Memory Store.

Stores typed MemoryItems and provides semantic search via SemanticIndex.
No autonomous learning loops — storage and retrieval only.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.memory.time_utils import normalize_datetime

from app.core.contracts.memory import MemoryItem, MemorySearchResult, MemoryType
from app.memory.semantic_index import SemanticIndex
from app.memory.semantic_metrics import SemanticMetricsCollector


class ContextMemoryStore:
    """Stores and semantically retrieves execution context memory items."""

    def __init__(self) -> None:
        self._items: dict[str, MemoryItem] = {}
        self._index = SemanticIndex()
        self._metrics = SemanticMetricsCollector()

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def save_context(self, item: MemoryItem) -> None:
        """Store a memory item and index it for semantic search.
        
        Items with retention_policy == "temporary" are NOT saved.
        """
        if item.retention_policy == "temporary":
            return
            
        item.updated_at = datetime.now(timezone.utc)
        self._items[item.id] = item
        self._index.index(
            item_id=item.id,
            text=item.content,
            metadata={"category": item.category.value, **item.metadata},
        )

    def update_memory(self, item: MemoryItem) -> None:
        """Update an existing memory item (or insert if missing)."""
        self.save_context(item)

    def delete_memory(self, item_id: str) -> None:
        """Remove a memory item from the store and index."""
        if item_id in self._items:
            del self._items[item_id]
            self._index.remove(item_id)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def search_context(
        self,
        query: str,
        top_k: int = 10,
        memory_type: MemoryType | None = None,
        allow_private: bool = False,
    ) -> list[MemorySearchResult]:
        """Semantic search over stored context items.

        Optionally filters by MemoryType category before ranking.
        Filters out retention_policy == "private" if allow_private is False.
        """
        filters = {"category": memory_type.value} if memory_type else None
        raw_results = self._index.search(query, top_k=top_k, filters=filters)

        results: list[MemorySearchResult] = []
        for item_id, score, matched_features in raw_results:
            item = self._items.get(item_id)
            if item:
                if not allow_private and item.retention_policy == "private":
                    continue
                results.append(MemorySearchResult(
                    item=item,
                    score=score,
                    matched_features=matched_features,
                ))

        top_score = results[0].score if results else 0.0
        self._metrics.record_search(len(results), top_score)
        return results

    def get(self, item_id: str) -> MemoryItem | None:
        """Return a stored item by ID regardless of recency window."""
        return self._items.get(item_id)

    def get_by_type(
        self,
        memory_type: str,
        n: int | None = None,
        allow_private: bool = False,
    ) -> list[MemoryItem]:
        """Return stored items of a given memory_type, newest first.

        Unlike ``get_recent_context`` this scans the full store, so typed
        items written before many unrelated writes are still found.  The
        ordering is deterministic (created_at desc, then id desc).
        """
        items = [
            it
            for it in self._items.values()
            if (it.metadata or {}).get("memory_type") == memory_type
            and (allow_private or it.retention_policy != "private")
        ]
        items.sort(key=lambda it: (normalize_datetime(getattr(it, "created_at", None)) or datetime.min.replace(tzinfo=timezone.utc), str(it.id)), reverse=True)
        return items[:n] if n is not None else items

    def get_recent_context(self, n: int = 10, allow_private: bool = False) -> list[MemoryItem]:
        """Return the n most recently created memory items."""
        items = self._items.values()
        if not allow_private:
            items = [it for it in items if it.retention_policy != "private"]
            
        sorted_items = sorted(
            items,
            key=lambda it: (normalize_datetime(getattr(it, "created_at", None)) or datetime.min.replace(tzinfo=timezone.utc), str(it.id)),
            reverse=True,
        )
        return sorted_items[:n]

    def get_metrics(self) -> dict:
        m = self._metrics.get_metrics()
        return m.model_dump()

    def __len__(self) -> int:
        return len(self._items)
