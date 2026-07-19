import uuid
from datetime import datetime
from typing import Any, List, Optional, Union

from app.core.contracts.memory import MemoryRecord
from app.core.contracts.skills import SkillRecord, SkillSearchResult
from app.memory.base import Memory
from app.memory.categories import normalize_category, normalize_category_for_storage
from app.memory.metrics import MemoryMetricsCollector, MemoryMetricsSnapshot
from app.memory.models import MemoryEntry
from app.memory.repository import MemoryRepository
from app.memory.search import search_entries
from app.memory.skills import SkillMemoryStore
from app.memory.store import InMemoryStore


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
            self._repo = MemoryRepository()
        self._metrics = MemoryMetricsCollector()
        self._skill_store = SkillMemoryStore()

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
        now = datetime.utcnow()
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
