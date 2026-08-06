"""Phase 12.1/12.3/12.7 — InternetTool facade.

A governed, provider-agnostic Tool bound to the pipeline CAP → SearchProvider
→ Cache → Rank → Verify → (optional) ContentFetch. The LLM never searches on
its own: it can only reason over the verified results this tool returns.

Governance: the tool refuses to run without a CAP permit decision injected by
the Orchestrator (``_cap_permit``), and it never raises — every SearchError is
turned into a graceful ToolResult the workflow can surface to the user.
"""

from __future__ import annotations

import logging
from typing import Any

from app.internet.brave import BraveSearchProvider
from app.internet.cache import SearchCache
from app.internet.fetcher import ContentFetcher
from app.internet.models import (
    SearchError,
    SearchResponse,
    SourceMetadata,
)
from app.internet.policy import SearchPolicy
from app.internet.provider import SearchProvider
from app.internet.ranker import ResultRanker
from app.internet.verifier import SearchVerifier
from app.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)

_GOVERNANCE_ERROR = (
    "Internet access requires CAP governance approval. "
    "No permit was attached to this request."
)
_DENIED_ERROR = "Internet access was denied by governance policy."


class InternetTool(Tool):
    """Governed internet-intelligence tool: search, news, suggest, fetch."""

    def __init__(
        self,
        provider: SearchProvider | None = None,
        policy: SearchPolicy | None = None,
        cache: SearchCache | None = None,
        ranker: ResultRanker | None = None,
        verifier: SearchVerifier | None = None,
        fetcher: ContentFetcher | None = None,
    ) -> None:
        self._provider = provider or BraveSearchProvider()
        self._policy = policy or SearchPolicy()
        self._cache = cache or SearchCache()
        self._ranker = ranker or ResultRanker(self._policy)
        self._verifier = verifier or SearchVerifier(self._policy)
        self._fetcher = fetcher or ContentFetcher()

    @property
    def name(self) -> str:
        return "internet"

    # ------------------------------------------------------------------
    # Tool interface
    # ------------------------------------------------------------------

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        action = str(arguments.get("action") or "search").strip().lower()
        query = str(arguments.get("query") or "").strip()

        if not self._policy.enabled:
            return ToolResult(ok=False, error="Internet access is disabled.")
        if not self._policy.allows_action(action):
            return ToolResult(
                ok=False, error=f"Unsupported internet action: {action}"
            )

        if not self._governed(arguments):
            return ToolResult(ok=False, error=_GOVERNANCE_ERROR)
        if str(arguments.get("_cap_permit") or "").lower() == "deny":
            return ToolResult(ok=False, error=_DENIED_ERROR)

        if action == "fetch":
            return await self._fetch(arguments)
        if action == "suggest":
            return await self._suggest(query)
        return await self._search(query, action, arguments)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def _search(
        self, query: str, action: str, arguments: dict[str, Any]
    ) -> ToolResult:
        category = "web" if action == "search" else action
        if not self._policy.allows_category(category):
            return ToolResult(
                ok=False, error=f"Category not allowed: {category}"
            )
        if not query:
            return ToolResult(ok=False, error="A non-empty query is required.")
        if len(query) > self._policy.max_query_length:
            return ToolResult(
                ok=False, error="Query exceeds the maximum allowed length."
            )
        if not self._provider.is_configured():
            return ToolResult(
                ok=False,
                error="No internet search provider is configured "
                "(set SAMAKTHA_BRAVE_API_KEY or inject a provider).",
            )

        max_results = self._policy.max_results
        cached = self._cache.get(category, query)
        if cached is not None:
            ranked = self._ranker.rank(cached)
            verified = self._verifier.verify(ranked)
            stamped = self._verifier.apply(ranked, verified)
            return ToolResult(
                ok=True,
                data=self._build_data(stamped, action, verified, cached=True),
            )

        try:
            if category == "news":
                response = await self._provider.news(
                    query, max_results=max_results
                )
            else:
                response = await self._provider.search(
                    query, max_results=max_results
                )
        except SearchError as exc:
            log.info("InternetTool: search failed — category=%s error=%s", category, exc)
            return ToolResult(ok=False, error=str(exc))
        except Exception as exc:  # pragma: no cover - defensive boundary
            log.warning("InternetTool: unexpected search failure: %s", exc, exc_info=True)
            return ToolResult(ok=False, error=f"Search failed: {exc}")

        ranked = self._ranker.rank(response)
        verified = self._verifier.verify(ranked)
        stamped = self._verifier.apply(ranked, verified)
        self._cache.put(
            category, query, stamped, ttl_seconds=self._policy.ttl_for(category)
        )
        return ToolResult(
            ok=True, data=self._build_data(stamped, action, verified, cached=False)
        )

    async def _fetch(self, arguments: dict[str, Any]) -> ToolResult:
        if not self._policy.allow_fetch:
            return ToolResult(ok=False, error="Content fetching is disabled.")
        url = str(arguments.get("url") or "").strip()
        if not url:
            return ToolResult(ok=False, error="A url is required for fetch.")
        result = await self._fetcher.fetch(url)
        if not result.ok:
            return ToolResult(ok=False, error=result.error or "Fetch failed.")
        return ToolResult(
            ok=True,
            data={
                "internet": True,
                "action": "fetch",
                "url": result.url,
                "title": result.title,
                "content": result.text,
                "content_type": result.content_type,
                "retrieved_at": result.retrieved_at,
            },
        )

    async def _suggest(self, query: str) -> ToolResult:
        if not self._policy.allow_suggestions:
            return ToolResult(ok=False, error="Suggestions are disabled.")
        if not query:
            return ToolResult(ok=False, error="A non-empty query is required.")
        try:
            suggestions = await self._provider.suggestions(query)
        except Exception:
            suggestions = []
        return ToolResult(
            ok=True,
            data={
                "internet": True,
                "action": "suggest",
                "query": query,
                "suggestions": suggestions,
            },
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _governed(self, arguments: dict[str, Any]) -> bool:
        if not self._policy.require_approval:
            return True
        return "_cap_permit" in arguments

    def _build_data(
        self,
        response: SearchResponse,
        action: str,
        verification,
        cached: bool,
    ) -> dict[str, Any]:
        sources = [
            SourceMetadata(
                title=result.title,
                url=result.url,
                domain=result.domain,
                retrieved_at=result.retrieved_at,
                published_at=result.published_at,
                confidence=result.confidence,
            ).model_dump()
            for result in response.results
        ]
        return {
            "internet": True,
            "action": action,
            "query": response.query,
            "results": [result.model_dump() for result in response.results],
            "sources": sources,
            "result_count": len(response.results),
            "cached": cached,
            "provider": response.source,
            "verification": verification.model_dump(),
        }
