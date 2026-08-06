import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional, Union

from app.core.contracts.memory import MemoryItem, MemoryRecord, MemorySearchResult, MemoryType
from app.core.contracts.skills import SkillRecord, SkillSearchResult
from app.memory.base import Memory
from app.memory.categories import normalize_category, normalize_category_for_storage
from app.memory.context import ContextMemoryStore
from app.memory.documents import DocumentMemoryStore, DocumentRecord
from app.memory.metrics import MemoryMetricsCollector, MemoryMetricsSnapshot
from app.memory.models import MemoryEntry
from app.memory.personal_knowledge import PersonalKnowledgeStore
from app.memory.repository import MemoryRepository
from app.memory.search import search_entries
from app.memory.skills import SkillMemoryStore
from app.memory.store import InMemoryStore

log = logging.getLogger(__name__)

_ENGLISH_STOP_WORDS: set[str] = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "but", "if", "or", "because",
    "as", "until", "while", "of", "at", "by", "for", "with", "about",
    "against", "between", "into", "through", "during", "before", "after",
    "above", "below", "to", "from", "up", "down", "in", "out", "on", "off",
    "over", "under", "again", "further", "then", "once", "here", "there",
    "when", "where", "why", "how", "all", "each", "every", "both", "few",
    "more", "most", "other", "some", "such", "no", "nor", "not", "only",
    "own", "same", "so", "than", "too", "very", "just", "and", "we", "you",
    "he", "she", "it", "they", "me", "him", "her", "us", "them", "my",
    "your", "his", "its", "our", "their", "this", "that", "these", "those",
    "i", "what", "which", "who", "whom", "would", "could", "should", "may",
    "might", "shall", "can", "need", "dare", "ought", "used", "will",
    "also", "am",
}

_SCORE_NAME_MATCH = 5
_SCORE_TAG_MATCH = 3
_SCORE_SUMMARY_MATCH = 2
_SCORE_METADATA_MATCH = 2


class MemoryManager(Memory):
    """Coordinates persistent memory operations (v0.2). Fulfills Memory and MemoryReader interfaces."""

    def __init__(
        self,
        store: Union[InMemoryStore, MemoryRepository, None] = None,
        *,
        repository: Optional[MemoryRepository] = None,
    ):
        if repository is not None:
            self._repo = repository
        elif isinstance(store, MemoryRepository):
            self._repo = store
        elif isinstance(store, InMemoryStore):
            self._repo = MemoryRepository(store=store)
        else:
            self._repo = MemoryRepository(store=InMemoryStore())
        self._metrics = MemoryMetricsCollector()
        self._skill_store = SkillMemoryStore()
        self._context_store = ContextMemoryStore()  # Phase 4.5
        self._document_store = DocumentMemoryStore()  # Phase 5.2
        self._knowledge_store = PersonalKnowledgeStore()  # Phase 14
        self._load_persisted_memories()

    def get_metrics(self) -> MemoryMetricsSnapshot:
        return self._metrics.get_metrics()

    def get_skill_metrics(self) -> dict[str, int]:
        return self._skill_store.get_metrics()

    async def read(self, key: str) -> Optional[MemoryRecord]:
        self._metrics.record_read()
        entry = self._repo.get(key)
        if entry is None:
            return None
        return self._entry_to_record(entry)

    async def write(self, key: str, value: Any, category: str = "internal") -> None:
        self._metrics.record_write()
        now = datetime.now(timezone.utc)
        stored_category = normalize_category_for_storage(category)
        entry = self._repo.get(key)
        if entry:
            entry.value = value
            entry.category = stored_category
            entry.updated_at = now
        else:
            entry = MemoryEntry(
                id=str(uuid.uuid4()),
                key=key,
                value=value,
                category=stored_category,
                created_at=now,
                updated_at=now,
                metadata={"source": "memory_manager"},
            )
        self._repo.save(entry)

    async def delete(self, key: str) -> None:
        self._metrics.record_delete()
        self._repo.delete(key)

    def _load_persisted_memories(self) -> None:
        """Restore context items, documents, and skills from SQLite on startup."""
        try:
            entries = self._repo.list_all()
        except Exception:
            return
        for entry in entries:
            try:
                if entry.key.startswith("mem:"):
                    raw = entry.metadata.get("_memory_item", "")
                    if isinstance(raw, str) and raw:
                        from app.core.contracts.memory import MemoryItem as MI
                        data = json.loads(raw)
                        item = MI(**data)
                        self._context_store._items[item.id] = item
                        self._context_store._index.index(
                            item.id,
                            item.content,
                            {"category": item.category.value, **item.metadata},
                        )
                elif entry.key.startswith("doc:"):
                    raw = entry.value
                    if isinstance(raw, str) and raw:
                        data = json.loads(raw)
                        from app.memory.documents import DocumentRecord as DR
                        record = DR(**data)
                        self._document_store._documents[record.document_id] = record
                elif entry.key.startswith("skill:"):
                    raw = entry.value
                    if isinstance(raw, str) and raw:
                        from app.core.contracts.skills import SkillRecord as SR
                        data = json.loads(raw)
                        skill = SR(**data)
                        self._skill_store._skills[skill.skill_id] = skill
                        self._skill_store._skill_index.index(
                            skill.skill_id,
                            f"{skill.name} {skill.description} {' '.join(skill.tags)}",
                            {"category": skill.category},
                        )
            except Exception:
                continue

    async def search(self, query: str = "", category: Optional[str] = None) -> List[MemoryRecord]:
        self._metrics.record_search()
        entries = self._repo.list_all()
        filter_category = (
            normalize_category_for_storage(category) if category is not None else None
        )
        filtered = search_entries(entries, query, filter_category)
        return [self._entry_to_record(entry) for entry in filtered]

    # ------------------------------------------------------------------
    # Skill Memory APIs — Core
    # ------------------------------------------------------------------

    def save_skill(self, skill: SkillRecord) -> None:
        self._skill_store.save_skill(skill)
        entry = MemoryEntry(
            id=skill.skill_id,
            key=f"skill:{skill.skill_id}",
            value=skill.model_dump_json(),
            category="skill",
            created_at=skill.created_at,
            updated_at=skill.updated_at,
        )
        self._repo.save(entry)

    def update_skill(self, skill: SkillRecord) -> None:
        self._skill_store.update_skill(skill)

    def get_skill(self, skill_id: str) -> Optional[SkillRecord]:
        return self._skill_store.get_skill(skill_id)

    def list_skills(self) -> list[SkillRecord]:
        return self._skill_store.list_skills()

    def search_skills(
        self,
        query: str = "",
        tag: str = "",
        category: str = ""
    ) -> list[SkillSearchResult]:
        if tag:
            return self._skill_store.search_by_tag(tag)
        if category:
            return self._skill_store.search_by_category(category)
        if query:
            return self._skill_store.search_by_name(query)
        return []

    def find_relevant_skills(
        self,
        goal: str,
        category: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> list[SkillSearchResult]:
        """Rank and filter ACTIVE skills relevant to a goal."""
        return self._skill_store.find_relevant_skills(goal, category, tags)

    # ------------------------------------------------------------------
    # Skill Memory APIs — Lifecycle
    # ------------------------------------------------------------------

    def record_skill_use(self, skill_id: str) -> None:
        self._skill_store.record_skill_use(skill_id)

    def record_skill_success(self, skill_id: str) -> None:
        self._skill_store.record_skill_success(skill_id)

    def record_skill_failure(self, skill_id: str) -> None:
        self._skill_store.record_skill_failure(skill_id)

    def deprecate_skill(self, skill_id: str, reason: str = "") -> None:
        self._skill_store.deprecate_skill(skill_id, reason)

    def archive_skill(self, skill_id: str) -> None:
        self._skill_store.archive_skill(skill_id)

    def merge_duplicate_skills(self, primary_id: str, duplicate_id: str) -> bool:
        return self._skill_store.merge_duplicate_skills(primary_id, duplicate_id)

    def run_lifecycle_maintenance(self, stale_days: int = 30) -> dict[str, int]:
        return self._skill_store.run_lifecycle_maintenance(stale_days)

    def list_deprecated_skills(self) -> list[SkillRecord]:
        return self._skill_store.list_deprecated_skills()

    def list_archived_skills(self) -> list[SkillRecord]:
        return self._skill_store.list_archived_skills()

    # ------------------------------------------------------------------
    # Semantic Memory APIs — Phase 4.5
    # ------------------------------------------------------------------

    def store_memory(self, item: MemoryItem) -> None:
        """Store a typed MemoryItem in the semantic context store."""
        self._context_store.save_context(item)
        entry = MemoryEntry(
            id=item.id,
            key=f"mem:{item.id}",
            value=item.content,
            category=item.category.value,
            created_at=item.created_at,
            updated_at=item.updated_at,
            metadata={"_memory_item": item.model_dump_json()},
        )
        self._repo.save(entry)

    def search_memory(
        self,
        query: str,
        top_k: int = 10,
        memory_type: MemoryType | None = None,
    ) -> list[MemorySearchResult]:
        """Semantic search over stored MemoryItems."""
        return self._context_store.search_context(query, top_k=top_k, memory_type=memory_type)

    def get_context_item(self, item_id: str) -> MemoryItem | None:
        """Return a stored context item by ID regardless of recency window.

        Used by the retriever to materialize semantic hits that fall outside
        the recent-memory window without losing them.
        """
        return self._context_store.get(item_id)

    def get_context_items_by_type(
        self,
        memory_type: str,
        n: int | None = None,
        allow_private: bool = False,
    ) -> list[MemoryItem]:
        """Return stored items of a given memory_type, newest first.

        Scans the full store so typed items are found even when they fall
        outside the recent-memory window.
        """
        return self._context_store.get_by_type(memory_type, n=n, allow_private=allow_private)

    def delete_memory(self, item_id: str) -> None:
        """Remove a MemoryItem by ID.

        Deletion is persistent: the in-memory ContextMemoryStore item and its
        semantic index entry are removed together with the SQLite ``mem:<id>``
        row, so the item never returns after a restart.
        """
        self._context_store.delete_memory(item_id)
        self._repo.delete(f"mem:{item_id}")

    def delete_memory_by_type(self, memory_type: str) -> int:
        """Permanently delete every memory item of a given type.

        Matches against the ``memory_type`` metadata value (conversation,
        preference, workflow, tool, knowledge, system, document, ...).
        Returns the number of items deleted.
        """
        removed = 0
        items = self._context_store.get_recent_context(n=1000, allow_private=True)
        for item in items:
            meta = item.metadata or {}
            if meta.get("memory_type") == memory_type:
                self.delete_memory(item.id)
                removed += 1
        return removed

    def delete_all_memories(self) -> dict[str, int]:
        """Permanently delete every persisted memory.

        Removes all SQLite rows (``mem:``, ``doc:``, ``skill:``) plus the
        in-memory context/document/skill stores and their indexes, so nothing
        can be re-hydrated on startup. Returns a count per storage family.
        """
        counts = {"mem": 0, "doc": 0, "skill": 0}
        for entry in self._repo.list_all():
            key = entry.key or ""
            try:
                if key.startswith("mem:"):
                    self._context_store.delete_memory(key[len("mem:"):])
                    self._repo.delete(key)
                    counts["mem"] += 1
                elif key.startswith("doc:"):
                    doc_id = key[len("doc:"):]
                    self._document_store.delete(doc_id)
                    self._repo.delete(key)
                    counts["doc"] += 1
                elif key.startswith("skill:"):
                    skill_id = key[len("skill:"):]
                    self._skill_store.delete_skill(skill_id)
                    self._repo.delete(key)
                    counts["skill"] += 1
            except Exception:
                log.debug("MemoryManager: delete_all_memories failed for %s", key, exc_info=True)
        return counts

    def update_memory(self, item: MemoryItem) -> None:
        """Update an existing MemoryItem (upsert)."""
        self._context_store.update_memory(item)

    def get_recent_context(
        self, n: int = 10, allow_private: bool = False
    ) -> list[MemoryItem]:
        """Return the n most recently stored context items."""
        return self._context_store.get_recent_context(n, allow_private=allow_private)

    # ------------------------------------------------------------------
    # Document Memory APIs — Phase 5.2
    # ------------------------------------------------------------------

    def store_document(self, record: DocumentRecord) -> DocumentRecord:
        """Persist a document metadata record."""
        stored = self._document_store.store(record)
        entry = MemoryEntry(
            id=record.document_id,
            key=f"doc:{record.document_id}",
            value=record.model_dump_json(),
            category="document",
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        self._repo.save(entry)
        return stored

    def get_document(self, document_id: str) -> Optional[DocumentRecord]:
        """Retrieve a document record by ID."""
        return self._document_store.get(document_id)

    def search_documents(self, query: str = "") -> list[DocumentRecord]:
        """Search stored documents by keyword scoring across name, tags, summary, and metadata.

        Extracts meaningful keywords from the query (ignoring stop words),
        computes a relevance score per document, and returns documents
        sorted by score descending.

        Falls back to returning all documents (by recency) when the query
        contains document-related terms (doc, file, pdf) but no keywords
        match any specific document.
        """
        query_lower = query.lower().strip()
        if not query_lower:
            return self._document_store.list_all()

        tokens = [
            t for t in re.findall(r"[a-z0-9]+", query_lower)
            if t not in _ENGLISH_STOP_WORDS and len(t) > 1
        ]

        if not tokens:
            return self._document_store.list_all()

        scored: list[tuple[DocumentRecord, int]] = []
        for doc in self._document_store.list_all():
            doc_name_lower = doc.name.lower()
            doc_stem = os.path.splitext(doc_name_lower)[0]
            doc_ext = os.path.splitext(doc_name_lower)[1].lstrip(".")

            score = 0
            for token in tokens:
                if token == doc_name_lower or token == doc_stem:
                    score += _SCORE_NAME_MATCH
                elif token in doc_stem:
                    score += _SCORE_NAME_MATCH

                if token == doc_ext:
                    score += _SCORE_TAG_MATCH

                if any(token in t.lower() for t in doc.tags):
                    score += _SCORE_TAG_MATCH

                if token in doc.summary.lower():
                    score += _SCORE_SUMMARY_MATCH

                for v in doc.metadata.values():
                    if isinstance(v, str) and token in v.lower():
                        score += _SCORE_METADATA_MATCH
                        break

            if score > 0:
                scored.append((doc, score))
                log.debug("search_documents: doc=%s score=%d", doc.name, score)

        if scored:
            scored.sort(key=lambda x: -x[1])
            results = [doc for doc, _ in scored]
            log.debug("search_documents: query=%r tokens=%s scored=%d", query, tokens, len(results))
            return results

        # Fallback: if the query contains document-related terms but no
        # keywords matched, return all documents sorted by recency.
        doc_terms = {"doc", "document", "file", "pdf", "read", "open", "show", "list", "history", "recent", "last", "analyse", "analyze", "summarize", "summarise"}
        if doc_terms & set(tokens):
            all_docs = self._document_store.list_all()
            log.debug("search_documents: no keyword match, fallback to %d recent docs for %r", len(all_docs), query)
            return all_docs

        log.debug("search_documents: no results for query=%r tokens=%s", query, tokens)
        return []

    def link_document_context(self, document_id: str, context_id: str) -> bool:
        """Associate a context memory item with a document."""
        return self._document_store.link_context(document_id, context_id)

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _entry_to_record(entry: MemoryEntry) -> MemoryRecord:
        return MemoryRecord(
            key=entry.key,
            content=str(entry.value),
            category=normalize_category(entry.category),
            metadata={
                "id": entry.id,
                "created_at": entry.created_at.isoformat(),
                "updated_at": entry.updated_at.isoformat(),
                "score": entry.score,
                **entry.metadata,
            },
        )

    def search_personal_knowledge(self, entity_type: str, query: str) -> list[Any]:
        """Search personal knowledge entities through the knowledge store."""
        return self._knowledge_store.search(entity_type, query)
