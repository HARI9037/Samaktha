"""SearXNG HTTP/JSON adapter for Samaktha's canonical SearchProvider boundary.

SearXNG remains a separately operated service. This adapter owns only trusted
endpoint validation, bounded HTTP transport, error mapping, and normalization;
CAP, Runtime, ranking, verification, and evidence stay upstream.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

import httpx

from app.internet.models import (
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

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_RETRYABLE_STATUS = frozenset({500, 502, 503, 504})
_DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_MAX_PROVIDER_RESULTS = 20


class SearXNGSearchProvider(SearchProvider):
    """Bounded async client for a trusted, operator-configured SearXNG service."""

    name = "searxng"

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = 15.0,
        max_retries: int = 2,
        max_response_bytes: int = 1_000_000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if timeout <= 0 or timeout > 60:
            raise ValueError("SearXNG timeout must be greater than 0 and at most 60 seconds.")
        if max_retries < 0 or max_retries > 5:
            raise ValueError("SearXNG max_retries must be between 0 and 5.")
        if max_response_bytes < 1 or max_response_bytes > 10_000_000:
            raise ValueError("SearXNG response bound must be between 1 and 10000000 bytes.")

        self._base_url = self._validate_base_url(base_url)
        self._timeout = float(timeout)
        self._max_retries = int(max_retries)
        self._max_response_bytes = int(max_response_bytes)
        self._transport = transport

    @property
    def endpoint_origin(self) -> str | None:
        """Return only the configured origin, suitable for safe diagnostics."""
        if not self._base_url:
            return None
        parsed = urlparse(self._base_url)
        return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))

    def is_configured(self) -> bool:
        return bool(self._base_url)

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
        # SearchProvider explicitly permits an empty suggestions surface. Do
        # not scrape or depend on an undocumented SearXNG autocomplete API.
        return []

    async def health(self) -> bool:
        if not self.is_configured():
            return False
        try:
            await self.search(
                "samaktha-health",
                max_results=1,
                timeout=min(self._timeout, 3.0),
            )
            return True
        except Exception:
            return False

    async def _request(
        self,
        category: str,
        query: str,
        max_results: int,
        timeout: float | None,
    ) -> SearchResponse:
        if not self.is_configured():
            raise SearchConfigError(
                "SearXNG search is not configured. Configure SAMAKTHA_SEARXNG_URL."
            )

        limit = max(1, min(int(max_results), _MAX_PROVIDER_RESULTS))
        endpoint = f"{self._base_url}/search"
        params: dict[str, str] = {
            "q": str(query),
            "format": "json",
            "categories": "news" if category == "news" else "general",
        }
        last_error: SearchHTTPError | SearchRateLimitError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                payload = await self._get(endpoint, params, timeout)
                return self._normalize(category, str(query), payload, limit)
            except (SearchRateLimitError, SearchHTTPError) as exc:
                last_error = exc
                retryable = isinstance(exc, SearchRateLimitError) or (
                    exc.status_code in _RETRYABLE_STATUS
                )
                if not retryable or attempt >= self._max_retries:
                    raise
                await asyncio.sleep(0.1 * (2**attempt))

        raise last_error  # pragma: no cover - loop always returns or raises

    async def _get(
        self,
        endpoint: str,
        params: dict[str, str],
        timeout: float | None,
    ) -> dict:
        effective_timeout = self._timeout if timeout is None else float(timeout)
        if effective_timeout <= 0 or effective_timeout > 60:
            raise SearchConfigError("SearXNG request timeout is outside the allowed range.")

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(effective_timeout),
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                async with client.stream(
                    "GET",
                    endpoint,
                    params=params,
                    headers={"Accept": "application/json"},
                ) as response:
                    self._raise_for_status(response.status_code)
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > self._max_response_bytes:
                            raise SearchProviderError(
                                "SearXNG response exceeded the configured size limit."
                            )
                        body.extend(chunk)
        except SearchProviderError:
            raise
        except SearchConfigError:
            raise
        except SearchRateLimitError:
            raise
        except SearchHTTPError:
            raise
        except httpx.TimeoutException as exc:
            raise SearchTimeoutError("SearXNG search timed out.") from exc
        except httpx.RequestError as exc:
            raise SearchNetworkError("SearXNG network request failed.") from exc

        try:
            payload = json.loads(bytes(body))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SearchProviderError("SearXNG returned malformed JSON.") from exc
        if not isinstance(payload, dict):
            raise SearchProviderError("SearXNG returned an unsupported JSON payload.")
        return payload

    @staticmethod
    def _raise_for_status(status_code: int) -> None:
        if status_code == 403:
            raise SearchConfigError(
                "SearXNG JSON API is unavailable or disabled on the configured instance."
            )
        if status_code == 429:
            raise SearchRateLimitError("SearXNG search rate limit reached (HTTP 429).")
        if status_code != 200:
            raise SearchHTTPError(status_code)

    def _normalize(
        self,
        category: str,
        query: str,
        payload: dict,
        max_results: int,
    ) -> SearchResponse:
        raw_results = payload.get("results", [])
        if not isinstance(raw_results, list):
            raise SearchProviderError("SearXNG returned an invalid results collection.")

        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        results: list[SearchResult] = []
        for item in raw_results:
            normalized = self._to_result(item, fetched_at)
            if normalized is None:
                continue
            results.append(normalized)
            if len(results) >= max_results:
                break

        unresponsive = payload.get("unresponsive_engines")
        failed_engines: list[str] = []
        if isinstance(unresponsive, list):
            for item in unresponsive[:16]:
                if isinstance(item, (list, tuple)) and item:
                    failed_engines.append(str(item[0])[:128])
                elif isinstance(item, str):
                    failed_engines.append(item[:128])
        return SearchResponse(
            query=query,
            category=category,
            results=results,
            total=len(results),
            source=self.name,
            fetched_at=fetched_at,
            metadata={
                "degraded": bool(failed_engines and results),
                "failed_engines": failed_engines,
            },
        )

    def _to_result(self, item: object, fetched_at: str) -> SearchResult | None:
        if not isinstance(item, dict):
            return None
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        parsed = urlparse(url)
        if (
            parsed.scheme.lower() not in _ALLOWED_SCHEMES
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            return None

        raw_score = item.get("score")
        score: float | None = None
        if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool):
            candidate = float(raw_score)
            if math.isfinite(candidate):
                score = candidate

        meta: dict[str, object] = {}
        engine = str(item.get("engine") or "").strip()
        if engine:
            meta["engine"] = engine[:128]
        engines = item.get("engines")
        if isinstance(engines, list):
            bounded = [str(value).strip()[:128] for value in engines[:8] if str(value).strip()]
            if bounded:
                meta["engines"] = bounded

        return SearchResult(
            title=title,
            url=url,
            description=str(item.get("content") or "").strip(),
            domain=(parsed.hostname or "").lower(),
            published_at=self._published_at(item.get("publishedDate")),
            retrieved_at=fetched_at,
            provider=self.name,
            score=score,
            meta=meta,
        )

    @staticmethod
    def _published_at(value: object) -> str | None:
        candidate = str(value or "").strip()
        match = _DATE_PREFIX.match(candidate)
        return match.group(1) if match else None

    @staticmethod
    def _validate_base_url(base_url: str | None) -> str:
        candidate = str(base_url or "").strip()
        if not candidate:
            return ""
        if any(character.isspace() for character in candidate):
            raise SearchConfigError("SearXNG URL is malformed.")

        parsed = urlparse(candidate)
        if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
            raise SearchConfigError("SearXNG URL must use http or https.")
        if not parsed.hostname:
            raise SearchConfigError("SearXNG URL must include a hostname.")
        if parsed.username or parsed.password:
            raise SearchConfigError("SearXNG URL must not contain embedded credentials.")
        if parsed.query or parsed.fragment:
            raise SearchConfigError("SearXNG URL must not contain a query or fragment.")
        try:
            parsed.port
        except ValueError as exc:
            raise SearchConfigError("SearXNG URL contains an invalid port.") from exc

        normalized_path = parsed.path.rstrip("/")
        return urlunparse(
            (
                parsed.scheme.lower(),
                parsed.netloc,
                normalized_path,
                "",
                "",
                "",
            )
        )
