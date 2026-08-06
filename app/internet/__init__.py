"""Phase 12 — Internet Intelligence package.

Provider-agnostic, governance-controlled internet access as a first-class
tool. The LLM never searches directly; it reasons only over verified results
produced by the InternetTool pipeline.
"""

from app.internet.brave import BraveSearchProvider
from app.internet.cache import SearchCache
from app.internet.fetcher import ContentFetcher
from app.internet.models import (
    FetchResult,
    SearchAuthError,
    SearchCancelledError,
    SearchConfigError,
    SearchConfidence,
    SearchError,
    SearchHTTPError,
    SearchNetworkError,
    SearchProviderError,
    SearchRateLimitError,
    SearchResponse,
    SearchResult,
    SearchTimeoutError,
    SourceMetadata,
    VerificationReport,
)
from app.internet.policy import SearchPolicy
from app.internet.provider import SearchProvider
from app.internet.ranker import ResultRanker
from app.internet.tool import InternetTool
from app.internet.verifier import SearchVerifier

__all__ = [
    "BraveSearchProvider",
    "ContentFetcher",
    "FetchResult",
    "InternetTool",
    "ResultRanker",
    "SearchAuthError",
    "SearchCache",
    "SearchCancelledError",
    "SearchConfigError",
    "SearchConfidence",
    "SearchError",
    "SearchHTTPError",
    "SearchNetworkError",
    "SearchPolicy",
    "SearchProvider",
    "SearchProviderError",
    "SearchRateLimitError",
    "SearchResponse",
    "SearchResult",
    "SearchTimeoutError",
    "SearchVerifier",
    "SourceMetadata",
    "VerificationReport",
]
