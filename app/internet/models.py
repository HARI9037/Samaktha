"""Phase 12.1 — Internet Intelligence core contracts.

Provider-agnostic data models shared by every search provider adapter and the
InternetTool facade. No provider-specific logic may ever live here.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SearchConfidence(StrEnum):
    """Deterministic confidence label assigned by the SearchVerifier.

    HIGH      — multiple independent authoritative sources agree
    MEDIUM    — at least one strong source, or partial agreement
    LOW       — single weak source, contradictions, or stale data
    UNKNOWN   — no verifiable evidence available
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class SearchResult(BaseModel):
    """A single normalized search result from any provider.

    This is the ONLY shape a provider may produce. Every adapter converts its
    raw payload into these fields; downstream ranking, verification, caching,
    context injection and memory all depend exclusively on this model.
    """

    title: str = ""
    url: str = ""
    description: str = ""
    domain: str = ""
    published_at: str | None = None
    retrieved_at: str = ""
    provider: str = ""
    score: float | None = None
    confidence: SearchConfidence = SearchConfidence.UNKNOWN
    duplicate_of: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    """Normalized response envelope returned by SearchProvider.search().

    ``results`` are pre-ranked and pre-verified by the InternetTool pipeline
    (never by the provider adapter itself).
    """

    query: str = ""
    category: str = "web"
    results: list[SearchResult] = Field(default_factory=list)
    total: int = 0
    source: str = ""
    fetched_at: str = ""
    error: str | None = None
    cached: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceMetadata(BaseModel):
    """Attribution data attached to an internet-sourced answer."""

    title: str = ""
    url: str = ""
    domain: str = ""
    retrieved_at: str = ""
    published_at: str | None = None
    confidence: SearchConfidence = SearchConfidence.UNKNOWN


class VerificationReport(BaseModel):
    """Outcome of the deterministic multi-source verification pass.

    ``verdict`` mirrors the strongest per-result confidence. ``per_result``
    maps a result URL to its confidence label. ``notes`` explains why the
    verdict was reached (never fabricated certainty).
    """

    verdict: SearchConfidence = SearchConfidence.UNKNOWN
    per_result: dict[str, SearchConfidence] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    agreeing_sources: int = 0
    conflicting_sources: int = 0


class FetchResult(BaseModel):
    """Outcome of a content-retrieval (ContentFetcher) request."""

    ok: bool
    url: str = ""
    title: str = ""
    text: str = ""
    content_type: str = ""
    error: str | None = None
    retrieved_at: str = ""


# ---------------------------------------------------------------------------
# Error hierarchy — every failure a search provider can surface maps onto one
# of these. The InternetTool converts every exception into a graceful
# ToolResult so the pipeline never crashes on network/provider failures.
# ---------------------------------------------------------------------------


class SearchError(Exception):
    """Base class for all internet-intelligence failures."""


class SearchConfigError(SearchError):
    """The search provider is not configured (e.g. missing API key)."""


class SearchNetworkError(SearchError):
    """Network-level failure: DNS, offline, timeout, connection reset."""


class SearchTimeoutError(SearchNetworkError):
    """The provider did not answer within the configured timeout."""


class SearchRateLimitError(SearchError):
    """The provider returned HTTP 429 or an explicit rate-limit signal."""


class SearchAuthError(SearchError):
    """The provider rejected the credentials (HTTP 401/403)."""


class SearchHTTPError(SearchError):
    """The provider returned an unexpected HTTP status."""

    def __init__(self, status_code: int, message: str = "") -> None:
        self.status_code = status_code
        super().__init__(message or f"Search provider HTTP {status_code}")


class SearchProviderError(SearchError):
    """The provider returned a malformed/unparseable payload."""


class SearchCancelledError(SearchError):
    """The search request was cancelled or aborted."""
