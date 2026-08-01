"""Phase 8 — Memory Cache.

Simple in-memory LRU-ish cache for recent memories, documents, skills,
and retrieval results.  Reduces unnecessary SQLite access.

All caches are bounded — when the limit is reached the oldest entry by
insertion order is evicted.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any


_MAX_RECENT_MEMORIES = 100
_MAX_RECENT_DOCUMENTS = 50
_MAX_RECENT_SKILLS = 50
_MAX_RETRIEVAL_RESULTS = 50


class _BoundedDict(OrderedDict):
    """Ordered dict that evicts oldest item when size exceeds maxlen."""

    def __init__(self, maxlen: int, *args, **kwargs):
        self._maxlen = maxlen
        super().__init__(*args, **kwargs)

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, value)
        if len(self) > self._maxlen:
            self.popitem(last=False)


class MemoryCache:
    """In-memory caches for the Memory Controller."""

    def __init__(
        self,
        max_memories: int = _MAX_RECENT_MEMORIES,
        max_documents: int = _MAX_RECENT_DOCUMENTS,
        max_skills: int = _MAX_RECENT_SKILLS,
        max_retrievals: int = _MAX_RETRIEVAL_RESULTS,
    ) -> None:
        self._recent_memories = _BoundedDict(maxlen=max_memories)
        self._recent_documents = _BoundedDict(maxlen=max_documents)
        self._recent_skills = _BoundedDict(maxlen=max_skills)
        self._retrieval_cache = _BoundedDict(maxlen=max_retrievals)
        self._hits = 0
        self._misses = 0

    # ------------------------------------------------------------------
    # Recent memories
    # ------------------------------------------------------------------

    def store_recent_memory(self, memory_id: str, item: Any) -> None:
        self._recent_memories[memory_id] = item

    def get_recent_memory(self, memory_id: str) -> Any | None:
        return self._recent_memories.get(memory_id)

    def clear_memories(self) -> None:
        self._recent_memories.clear()

    def list_cached_memories(self) -> list[Any]:
        return list(self._recent_memories.values())

    def memory_count(self) -> int:
        return len(self._recent_memories)

    # ------------------------------------------------------------------
    # Recent documents
    # ------------------------------------------------------------------

    def store_recent_document(self, doc_id: str, record: Any) -> None:
        self._recent_documents[doc_id] = record

    def get_recent_document(self, doc_id: str) -> Any | None:
        return self._recent_documents.get(doc_id)

    def clear_documents(self) -> None:
        self._recent_documents.clear()

    def document_count(self) -> int:
        return len(self._recent_documents)

    # ------------------------------------------------------------------
    # Recent skills
    # ------------------------------------------------------------------

    def store_recent_skill(self, skill_id: str, record: Any) -> None:
        self._recent_skills[skill_id] = record

    def get_recent_skill(self, skill_id: str) -> Any | None:
        return self._recent_skills.get(skill_id)

    def list_cached_skills(self) -> list[Any]:
        return list(self._recent_skills.values())

    def clear_skills(self) -> None:
        self._recent_skills.clear()

    def skill_count(self) -> int:
        return len(self._recent_skills)

    # ------------------------------------------------------------------
    # Retrieval results (query → list of results)
    # ------------------------------------------------------------------

    def store_retrieval(self, query_key: str, results: list[Any]) -> None:
        self._retrieval_cache[query_key] = results

    def get_retrieval(self, query_key: str) -> list[Any] | None:
        return self._retrieval_cache.get(query_key)

    def clear_retrievals(self) -> None:
        self._retrieval_cache.clear()

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def record_hit(self) -> None:
        self._hits += 1

    def record_miss(self) -> None:
        self._misses += 1

    @property
    def hit_count(self) -> int:
        return self._hits

    @property
    def miss_count(self) -> int:
        return self._misses

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return round(self._hits / total, 4) if total > 0 else 0.0

    def clear_all(self) -> None:
        self.clear_memories()
        self.clear_documents()
        self.clear_skills()
        self.clear_retrievals()
