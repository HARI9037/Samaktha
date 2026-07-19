from typing import Optional, List, Protocol

from app.memory.models import MemoryEntry
from app.memory.sqlite_store import SQLiteStore


class MemoryStore(Protocol):
    def store_entry(self, entry: MemoryEntry) -> None: ...

    def retrieve_entry(self, key: str) -> Optional[MemoryEntry]: ...

    def delete_entry(self, key: str) -> None: ...

    def list_entries(self) -> List[MemoryEntry]: ...


class MemoryRepository:
    def __init__(self, store: Optional[MemoryStore] = None):
        self._store = store or SQLiteStore()

    def save(self, entry: MemoryEntry) -> None:
        self._store.store_entry(entry)

    def get(self, key: str) -> Optional[MemoryEntry]:
        return self._store.retrieve_entry(key)

    def delete(self, key: str) -> None:
        self._store.delete_entry(key)

    def list_all(self) -> List[MemoryEntry]:
        return self._store.list_entries()

    def search(self, query: str = "", category: Optional[str] = None) -> List[MemoryEntry]:
        # Case insensitive search and category filter
        entries = self._store.list_entries()
        matches = []
        query_lower = query.lower()
        for entry in entries:
            if (not query or query_lower in str(entry.value).lower() or query_lower in entry.key.lower()):
                if (category is None) or (entry.category == category):
                    matches.append(entry)
        return matches
