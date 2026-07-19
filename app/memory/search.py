from typing import List, Optional
from app.memory.models import MemoryEntry


def search_entries(entries: List[MemoryEntry], query: str = "", category: Optional[str] = None) -> List[MemoryEntry]:
    query_lower = query.lower().strip() if query else ""
    results = []
    for entry in entries:
        if query_lower:
            # Match keyword in key or value
            key_match = query_lower in entry.key.lower()
            value_match = query_lower in str(entry.value).lower()
            if key_match or value_match:
                if category is None or entry.category == category:
                    entry.score = float(2 if key_match else 1)
                    results.append(entry)
        else:
            if category is None or entry.category == category:
                entry.score = 1.0
                results.append(entry)
    return sorted(results, key=lambda entry: (-entry.score, entry.key))
