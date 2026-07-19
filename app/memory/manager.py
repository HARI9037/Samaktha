import uuid
from datetime import datetime
from typing import Any, List, Optional, Union

from app.core.contracts.memory import MemoryRecord
from app.memory.base import Memory
from app.memory.categories import normalize_category, normalize_category_for_storage
from app.memory.models import MemoryEntry
from app.memory.repository import MemoryRepository
from app.memory.search import search_entries
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

    async def read(self, key: str) -> Optional[MemoryRecord]:
        entry = self._repo.get(key)
        if entry is None:
            return None
        return self._entry_to_record(entry)

    async def write(self, key: str, value: Any, category: str = "internal") -> None:
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
            )
        self._repo.save(entry)

    async def delete(self, key: str) -> None:
        self._repo.delete(key)

    async def search(self, query: str = "", category: Optional[str] = None) -> List[MemoryRecord]:
        entries = self._repo.list_all()
        filter_category = (
            normalize_category_for_storage(category) if category is not None else None
        )
        filtered = search_entries(entries, query, filter_category)
        return [self._entry_to_record(entry) for entry in filtered]

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
            },
        )
