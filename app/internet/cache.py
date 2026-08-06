"""Phase 12.9 — deterministic search-result cache.

Caching is governed entirely by SearchPolicy TTLs. Keys are derived from the
normalized query + category so the same user request always hits the same
entry, and every entry carries an expiry so stale results are never served.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from app.internet.models import SearchResponse


class SearchCache:
    """In-memory, TTL-bounded cache of normalized search responses."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], tuple[float, SearchResponse]] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._stored = 0
        self._evicted = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, category: str, query: str) -> SearchResponse | None:
        """Return a live cached response, or None on miss/expiry."""
        key = self._key(category, query)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None
            expires_at, response = entry
            if time.time() > expires_at:
                del self._entries[key]
                self._evicted += 1
                self._misses += 1
                return None
            self._hits += 1
            return response

    def put(
        self,
        category: str,
        query: str,
        response: SearchResponse,
        ttl_seconds: int = 300,
    ) -> None:
        """Store ``response`` for ``category``/``query`` with the given TTL."""
        key = self._key(category, query)
        expires_at = time.time() + max(0, int(ttl_seconds))
        with self._lock:
            self._entries[key] = (expires_at, response)
            self._stored += 1

    def invalidate(self, category: str | None = None, query: str | None = None) -> int:
        """Drop entries matching the optional category/query filters.

        Returns the number of entries removed.
        """
        removed = 0
        with self._lock:
            if category is None and query is None:
                removed = len(self._entries)
                self._entries.clear()
                return removed
            for key in [k for k in self._entries if self._matches(k, category, query)]:
                del self._entries[key]
                removed += 1
        return removed

    def clear(self) -> int:
        """Remove every cached entry. Returns the number removed."""
        return self.invalidate()

    def stats(self) -> dict[str, Any]:
        """Diagnostics snapshot (hits/misses/stored/evicted/live)."""
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "stored": self._stored,
                "evicted": self._evicted,
                "live_entries": len(self._entries),
            }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _key(category: str, query: str) -> tuple[str, str]:
        return (str(category).strip().lower(), SearchCache._normalize_query(query))

    @staticmethod
    def _normalize_query(query: str) -> str:
        """Deterministic query key: lowercase, punctuation-free, single spaces."""
        import re

        normalized = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", query)).strip().lower()
        return normalized or query.strip().lower()

    @staticmethod
    def _matches(
        key: tuple[str, str],
        category: str | None,
        query: str | None,
    ) -> bool:
        key_category, key_query = key
        if category is not None and key_category != category.strip().lower():
            return False
        if query is not None and key_query != SearchCache._normalize_query(query):
            return False
        return True
