from typing import List, Optional
from app.memory.models import MemoryEntry


def search_entries(entries: List[MemoryEntry], query: str = "", category: Optional[str] = None) -> List[MemoryEntry]:
    query_lower = query.lower().strip() if query else ""
    results = []
    for entry in entries:
        if query_lower:
            # Match keyword in key or value
            if query_lower in entry.key.lower() or query_lower in str(entry.value).lower():
                if category is None or entry.category == category:
                    results.append(entry)
        else:
            if category is None or entry.category == category:
                results.append(entry)
    return results
