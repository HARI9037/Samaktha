from typing import Dict, List, Optional

from app.memory.models import MemoryEntry


class InMemoryStore:
    """A simple in-memory store for memory entries."""

    def __init__(self) -> None:
        self._store: Dict[str, MemoryEntry] = {}

    def store_entry(self, entry: MemoryEntry) -> None:
        """Store an entry by its key."""
        self._store[entry.key] = entry

    def retrieve_entry(self, key: str) -> Optional[MemoryEntry]:
        """Retrieve an entry by its key."""
        return self._store.get(key)

    def delete_entry(self, key: str) -> None:
        """Delete an entry by its key."""
        if key in self._store:
            del self._store[key]

    def list_entries(self) -> List[MemoryEntry]:
        """List all stored memory entries."""
        return list(self._store.values())
