"""Phase 12.2 — Brave Search provider adapter.

The ONLY place Brave-specific knowledge lives. Converts Brave's web/news JSON
payloads into the provider-agnostic SearchResult/SearchResponse models and
maps every failure mode (auth, rate limit, HTTP, malformed JSON, timeout,
network) onto the SearchError hierarchy. No ranking, caching, verification or
governance logic lives here.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from app.internet.models import (
    SearchAuthError,
    SearchConfigError,
    SearchHTTPError,
    SearchNetworkError,
    SearchProviderError,
    SearchRateLimitError,
    SearchResponse,
    SearchResult,
    SearchTimeoutError,
)
from app.internet.provider import SearchProvider

log = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.search.brave.com/res/v1"
_SUBSCRIPTION_HEADER = "X-Subscription-Token"
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class BraveSearchProvider(SearchProvider):
    """Async adapter for the Brave Search API (web, news, suggestions)."""

    name = "brave"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: float = 15.0,
        max_retries: int = 2,
        base_url: str = _DEFAULT_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._timeout = timeout
        self._max_retries = max_retries
        self._base_url = base_url.rstrip("/")
        self._transport = transport

    # ------------------------------------------------------------------
    # SearchProvider interface
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        timeout: float | None = None,
    ) -> SearchResponse:
        return await self._request("web", query, max_results, timeout)

    async def news(
        self,
        query: str,
        *,
        max_results: int = 5,
        timeout: float | None = None,
    ) -> SearchResponse:
        return await self._request("news", query, max_results, timeout)

    async def suggestions(
        self,
        query: str,
        *,
        timeout: float | None = None,
    ) -> list[str]:
        """Return related-query suggestions from Brave (best-effort, optional)."""
        try:
            payload = await self._request(
                "web", query, max_results=1, timeout=timeout, suggestions=True
            )
        except Exception:
            return []
        raw = getattr(payload, "metadata", {})
        suggestions = raw.get("suggestions") if isinstance(raw, dict) else None
        if isinstance(suggestions, list):
            return [str(s) for s in suggestions if str(s).strip()]
        return []

    async def health(self) -> bool:
        if not self.is_configured():
            return False
        try:
            await self.search("samaktha", max_results=1, timeout=5.0)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Request plumbing
    # ------------------------------------------------------------------

    async def _request(
        self,
        category: str,
        query: str,
        max_results: int,
        timeout: float | None,
        suggestions: bool = False,
    ) -> SearchResponse:
        if not self.is_configured():
            raise SearchConfigError(
                "Brave Search is not configured (SAMAKTHA_BRAVE_API_KEY missing)."
            )

        endpoint = "web/search" if category == "web" else "news/search"
        url = f"{self._base_url}/{endpoint}"
        params: dict[str, object] = {
            "q": query,
            "count": max(1, min(max_results, 20)),
            "format": "json",
        }
        if suggestions:
            params["suggestions"] = 1
        headers = {
            _SUBSCRIPTION_HEADER: self._api_key,
            "Accept": "application/json",
        }

        last_error: SearchHTTPError | SearchNetworkError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._get(url, params, headers, timeout)
                return self._normalize(category, query, response)
            except (SearchRateLimitError, SearchHTTPError) as exc:
                last_error = exc
                retryable = isinstance(exc, SearchRateLimitError) or (
                    isinstance(exc, SearchHTTPError)
                    and exc.status_code in _RETRYABLE_STATUS
                )
                if not retryable or attempt >= self._max_retries:
                    raise
                await self._backoff(attempt)
            except SearchNetworkError:
                raise

        raise last_error  # pragma: no cover - loop always returns or raises

    async def _get(
        self,
        url: str,
        params: dict[str, object],
        headers: dict[str, str],
        timeout: float | None,
    ) -> dict:
        effective_timeout = timeout if timeout is not None else self._timeout
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(effective_timeout),
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                response = await client.get(url, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise SearchTimeoutError(f"Brave Search timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise SearchNetworkError(f"Brave Search network failure: {exc}") from exc

        if response.status_code == 401 or response.status_code == 403:
            raise SearchAuthError(
                f"Brave Search rejected the API key (HTTP {response.status_code})."
            )
        if response.status_code == 429:
            raise SearchRateLimitError("Brave Search rate limit reached (HTTP 429).")
        if response.status_code != 200:
            raise SearchHTTPError(response.status_code)

        try:
            return response.json()
        except ValueError as exc:
            raise SearchProviderError(
                f"Brave Search returned malformed JSON: {exc}"
            ) from exc

    @staticmethod
    async def _backoff(attempt: int) -> None:
        import asyncio

        await asyncio.sleep(0.5 * (2 ** attempt))

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def _normalize(
        self, category: str, query: str, payload: dict
    ) -> SearchResponse:
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        raw_results: list[dict] = []
        if category == "web":
            raw_results = payload.get("web", {}).get("results", []) or []
        else:
            raw_results = payload.get("news", {}).get("results", []) or []

        results = [
            self._to_result(item, category, fetched_at)
            for item in raw_results
            if isinstance(item, dict) and item.get("url")
        ]

        return SearchResponse(
            query=query,
            category=category,
            results=results,
            total=len(results),
            source=self.name,
            fetched_at=fetched_at,
            metadata=(
                {"suggestions": payload.get("suggestions", [])}
                if isinstance(payload.get("suggestions"), list)
                else {}
            ),
        )

    def _to_result(
        self, item: dict, category: str, fetched_at: str
    ) -> SearchResult:
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        description = str(item.get("description") or "").strip()

        meta_url = item.get("meta_url")
        domain = ""
        if isinstance(meta_url, dict):
            domain = str(meta_url.get("netloc") or meta_url.get("host") or "").lower()
        if not domain:
            parsed = urlparse(url)
            domain = (parsed.hostname or "").lower()

        published_at = self._published_at(item, category)
        return SearchResult(
            title=title,
            url=url,
            description=description,
            domain=domain,
            published_at=published_at,
            retrieved_at=fetched_at,
            provider=self.name,
        )

    @staticmethod
    def _published_at(item: dict, category: str) -> str | None:
        candidate = ""
        if category == "news":
            candidate = str(item.get("publish_time") or item.get("age") or "")
        else:
            candidate = str(item.get("page_age") or item.get("age") or "")
        candidate = candidate.strip()
        if not candidate:
            return None
        match = _ISO_DATE_RE.match(candidate)
        if match:
            return candidate[:10]
        return None
