"""DDGS adapter for Samaktha's canonical SearchProvider boundary.

DDGS is a zero-key metasearch dependency.  This module is the only production
layer that imports it.  CAP approval, runtime dispatch, retry policy, ranking,
verification, evidence, and grounded synthesis remain outside the adapter.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

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
    SearchUnknownError,
)
from app.internet.provider import SearchProvider

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_HTTP_STATUS = re.compile(r"\b(?:http\D*)?([1-5]\d{2})\b", re.IGNORECASE)
_MAX_PROVIDER_RESULTS = 20
_MAX_TIMEOUT_SECONDS = 60.0
_SAFE_DIAGNOSTIC_TOKEN = re.compile(r"[^A-Za-z0-9_.-]+")

log = logging.getLogger(__name__)


class _DDGSStageFailure(Exception):
    """Carry a bounded adapter stage without rendering the original error."""

    def __init__(self, stage: str, original: Exception) -> None:
        super().__init__("DDGS adapter stage failed.")
        self.stage = stage
        self.original = original


class DDGSSearchProvider(SearchProvider):
    """Bounded async adapter over the maintained :mod:`ddgs` package.

    Uses DuckDuckGo as the default backend for both web and news search.
    """

    name = "ddgs"

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        client_factory: Callable[..., Any] | None = None,
        backend: str = "duckduckgo",
    ) -> None:
        self._timeout = self._validate_timeout(timeout)
        self._client_factory = client_factory
        self._backend = backend

    def is_configured(self) -> bool:
        """DDGS needs neither an operator endpoint nor an API key.

        Configuration readiness is deliberately independent of dynamic module
        discovery.  The declared dependency is imported at the adapter boundary
        so an unavailable installation produces a typed ``SearchConfigError``
        instead of making a correctly composed provider look absent.
        """
        return True

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

    async def health(self) -> bool:
        """Configuration health is intentionally offline and side-effect free."""
        return True

    async def _request(
        self,
        category: str,
        query: str,
        max_results: int,
        timeout: float | None,
    ) -> SearchResponse:
        normalized_query = str(query).strip()
        if not normalized_query:
            raise SearchConfigError("DDGS search requires a non-empty query.")
        effective_timeout = self._validate_timeout(
            self._timeout if timeout is None else timeout
        )
        limit = max(1, min(int(max_results), _MAX_PROVIDER_RESULTS))

        try:
            raw_results = await asyncio.wait_for(
                asyncio.to_thread(
                    self._search_sync,
                    category,
                    normalized_query,
                    limit,
                    effective_timeout,
                ),
                timeout=effective_timeout,
            )
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError as exc:
            self._raise_mapped(exc, category=category, stage="provider_call")
        except _DDGSStageFailure as failure:
            if "no results found" in str(failure.original).casefold():
                raw_results = []
            else:
                self._raise_mapped(
                    failure.original,
                    category=category,
                    stage=failure.stage,
                )
        except OSError as exc:
            self._raise_mapped(exc, category=category, stage="provider_call")
        except Exception as exc:
            if "no results found" in str(exc).casefold():
                raw_results = []
            else:
                self._raise_mapped(exc, category=category, stage="provider_call")

        try:
            return self._normalize(category, normalized_query, raw_results, limit)
        except Exception as exc:
            self._raise_mapped(exc, category=category, stage="normalization")

    def _search_sync(
        self,
        category: str,
        query: str,
        max_results: int,
        timeout: float,
    ) -> object:
        # RuntimeEngine owns semantic retries.  Each adapter invocation makes
        # exactly one bounded DDGS operation and never falls back to a second
        # Samaktha SearchProvider.
        factory = self._client_factory
        if factory is None:
            try:
                from ddgs import DDGS
            except ImportError as exc:
                raise _DDGSStageFailure("dependency_import", exc) from exc
            factory = DDGS
        try:
            client = factory(timeout=max(1, math.ceil(timeout)), verify=True)
        except Exception as exc:
            raise _DDGSStageFailure("client_construction", exc) from exc
        try:
            method = client.news if category == "news" else client.text
        except Exception as exc:
            raise _DDGSStageFailure("method_selection", exc) from exc
        # Use configured backend (default: duckduckgo) instead of "auto"
        try:
            return method(query, max_results=max_results, backend=self._backend)
        except Exception as exc:
            raise _DDGSStageFailure("provider_call", exc) from exc

    def _normalize(
        self,
        category: str,
        query: str,
        payload: object,
        max_results: int,
    ) -> SearchResponse:
        if not isinstance(payload, list):
            raise SearchProviderError("DDGS returned an unsupported result payload.")

        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        results: list[SearchResult] = []
        for item in payload:
            normalized = self._to_result(item, category, fetched_at)
            if normalized is None:
                continue
            results.append(normalized)
            if len(results) >= max_results:
                break

        return SearchResponse(
            query=query,
            category=category,
            results=results,
            total=len(results),
            source=self.name,
            fetched_at=fetched_at,
        )

    def _to_result(
        self,
        item: object,
        category: str,
        fetched_at: str,
    ) -> SearchResult | None:
        if not isinstance(item, dict):
            return None
        url_key = "url" if category == "news" else "href"
        url = self._bounded_text(item.get(url_key), 2_048)
        parsed = urlparse(url)
        if (
            parsed.scheme.casefold() not in _ALLOWED_SCHEMES
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            return None

        meta: dict[str, str] = {}
        publisher = self._bounded_text(item.get("source"), 128)
        if publisher:
            meta["publisher"] = publisher

        return SearchResult(
            title=self._bounded_text(item.get("title"), 500),
            url=url,
            description=self._bounded_text(item.get("body"), 4_000),
            domain=(parsed.hostname or "").casefold()[:255],
            published_at=self._published_at(item.get("date")) if category == "news" else None,
            retrieved_at=fetched_at,
            provider=self.name,
            meta=meta,
        )

    @staticmethod
    def _published_at(value: object) -> str | None:
        match = _DATE_PREFIX.match(str(value or "").strip())
        return match.group(1) if match else None

    @staticmethod
    def _bounded_text(value: object, limit: int) -> str:
        return str(value or "").strip()[:limit]

    @staticmethod
    def _validate_timeout(value: object) -> float:
        try:
            timeout = float(value)
        except (TypeError, ValueError) as exc:
            raise SearchConfigError("DDGS request timeout is invalid.") from exc
        if not math.isfinite(timeout) or timeout <= 0 or timeout > _MAX_TIMEOUT_SECONDS:
            raise SearchConfigError(
                "DDGS request timeout must be greater than 0 and at most 60 seconds."
            )
        return timeout

    def _raise_mapped(self, exc: Exception, *, category: str, stage: str) -> None:
        mapped = self._map_sanitized(exc, stage=stage)
        log.warning(
            "DDGS failure: provider=ddgs backend=%s category=%s "
            "failure_stage=%s exception_type=%s mapped_error_type=%s",
            self._safe_diagnostic_token(self._backend),
            self._safe_diagnostic_token(category),
            self._safe_diagnostic_token(stage),
            self._safe_diagnostic_token(type(exc).__name__),
            self._safe_diagnostic_token(type(mapped).__name__),
        )
        if mapped is exc:
            raise mapped
        raise mapped from exc

    @staticmethod
    def _map_sanitized(exc: Exception, *, stage: str) -> Exception:
        if isinstance(exc, SearchProviderError):
            return exc
        if stage == "dependency_import" and isinstance(exc, ImportError):
            return SearchConfigError(
                "DDGS search dependency is unavailable; install the declared ddgs package."
            )
        text = str(exc).casefold()
        exception_name = type(exc).__name__.casefold()
        if "ratelimit" in exception_name or "rate limit" in text or "ratelimit" in text or "429" in text:
            return SearchRateLimitError("DDGS search rate limit reached.")
        if "timeout" in exception_name or "timed out" in text or "timeout" in text:
            return SearchTimeoutError("DDGS search timed out.")
        if any(token in text for token in ("401", "403", "unauthorized", "forbidden")):
            return SearchAuthError("DDGS upstream search authentication failed.")
        status = _HTTP_STATUS.search(text)
        if status:
            return SearchHTTPError(int(status.group(1)))
        if any(
            token in text
            for token in ("connection", "connect", "dns", "network", "offline", "reset")
        ):
            return SearchNetworkError("DDGS search network request failed.")
        return SearchUnknownError("DDGS search provider failed.")

    @staticmethod
    def _safe_diagnostic_token(value: object) -> str:
        token = _SAFE_DIAGNOSTIC_TOKEN.sub("_", str(value or "unknown"))
        return token[:80] or "unknown"
