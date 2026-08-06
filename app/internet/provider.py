"""Phase 12.1 — SearchProvider abstraction.

Every search provider (BraveSearchProvider today, any provider tomorrow) is a
stateless async adapter that normalizes its raw payload into SearchResponse /
SearchResult. No planning, ranking, verification or governance logic may live
in a provider adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.internet.models import SearchResponse


class SearchProvider(ABC):
    """Provider-agnostic search interface consumed by the InternetTool."""

    name: str = "unknown"

    @abstractmethod
    def is_configured(self) -> bool:
        """True when the provider holds the credentials it needs."""
        raise NotImplementedError

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        timeout: float | None = None,
    ) -> SearchResponse:
        """Perform a general web search for ``query``.

        Returns a normalized SearchResponse. Never raises a bare exception:
        provider failures are mapped onto the SearchError hierarchy by the
        adapter so the InternetTool can degrade gracefully.
        """
        raise NotImplementedError

    async def news(
        self,
        query: str,
        *,
        max_results: int = 5,
        timeout: float | None = None,
    ) -> SearchResponse:
        """Search recent news for ``query``.

        Adapters without a dedicated news surface fall back to ``search``.
        """
        return await self.search(query, max_results=max_results, timeout=timeout)

    async def suggestions(
        self,
        query: str,
        *,
        timeout: float | None = None,
    ) -> list[str]:
        """Return related query suggestions for ``query`` (may be empty)."""
        return []

    async def health(self) -> bool:
        """Cheap liveness probe used by diagnostics (default: configured?)."""
        return self.is_configured()
