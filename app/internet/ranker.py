"""Phase 12.5 — deterministic search-result ranking.

The ranker is a pure, stateless, provider-agnostic function. Given a normalized
SearchResponse it scores each result across six axes — relevance, freshness,
authority, language fit, completeness and duplication — and returns the same
input shape with ``score`` populated and duplicates collapsed. Identical input
always yields an identical ordering.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from app.internet.models import SearchConfidence, SearchResponse, SearchResult
from app.internet.policy import SearchPolicy

_TOKEN_SPLIT = re.compile(r"[^\w]+")
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")

# Non-authoritative host markers that drag a result's authority score down.
_LOW_AUTHORITY_MARKERS = (
    "reddit.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "instagram.com",
    "youtube.com",
    "pinterest.com",
    "quora.com",
    "tumblr.com",
    "sponsored",
    "ad.",
)


class ResultRanker:
    """Deterministic six-axis ranker with duplication collapse."""

    def __init__(self, policy: SearchPolicy | None = None) -> None:
        self._policy = policy or SearchPolicy()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rank(self, response: SearchResponse) -> SearchResponse:
        """Score, deduplicate, and sort a copy of the response. Never mutates
        the caller's objects (provider adapters may reuse cached instances).

        Only true duplicates — same normalized title from the same domain —
        are collapsed (keeping the best-scoring representative; on an exact
        score tie the first-seen result wins). Identical headlines from
        different domains are independent corroborating sources and survive,
        which is exactly what the verifier needs.
        """
        best: dict[tuple[str, str], SearchResult] = {}
        for result in response.results:
            if not result.url:
                continue
            dedup_key = (
                self._normalize_title(result.title),
                (result.domain or "").lower(),
            )
            score = round(self._score(result, response.query), 6)
            candidate = result.model_copy(update={"score": score})
            existing = best.get(dedup_key)
            if existing is None or score > (existing.score or 0.0):
                best[dedup_key] = candidate

        ranked = list(best.values())
        ranked.sort(key=lambda r: (-(r.score or 0.0), r.url))
        ranked = ranked[: max(1, self._policy.max_results)]

        return response.model_copy(
            update={
                "results": ranked,
                "total": len(ranked),
            }
        )

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score(self, result: SearchResult, query: str) -> float:
        query_tokens = self._tokens(query)
        relevance = self._relevance(result, query_tokens)
        freshness = self._freshness(result)
        authority = self._authority(result)
        language = self._language_fit(result, query)
        completeness = self._completeness(result)
        return (
            relevance * 5.0
            + authority * 3.0
            + freshness * 1.5
            + completeness * 1.0
            + language * 0.5
        )

    def _relevance(self, result: SearchResult, query_tokens: set[str]) -> float:
        if not query_tokens:
            return 0.0
        title_tokens = self._tokens(result.title)
        body_tokens = self._tokens(result.description)
        title_hits = len(title_tokens & query_tokens)
        body_hits = len(body_tokens & query_tokens)
        total = title_hits * 2 + body_hits
        max_possible = len(query_tokens) * 2
        return min(1.0, total / max_possible) if max_possible else 0.0

    def _freshness(self, result: SearchResult) -> float:
        published_at = result.published_at or ""
        match = _DATE_RE.match(published_at)
        if not match:
            return 0.5
        try:
            published = datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3)),
                tzinfo=timezone.utc,
            )
        except ValueError:
            return 0.5
        days = (datetime.now(timezone.utc) - published).days
        if days < 0:
            return 0.5
        if days <= 30:
            return 1.0
        if days <= 365:
            return 0.7
        if days <= 365 * 2:
            return 0.4
        return 0.2

    def _authority(self, result: SearchResult) -> float:
        domain = result.domain.lower()
        host = domain.split(":", 1)[0]
        for marker in _LOW_AUTHORITY_MARKERS:
            if marker in host:
                return 0.1
        root = host.split(".")[-2:] if host.count(".") >= 1 else [host]
        suffix = ".".join(root)
        if domain in self._policy.authoritative_domains or suffix in {
            ".gov", ".edu", ".org"
        }:
            return 1.0
        return 0.6

    def _language_fit(self, result: SearchResult, query: str) -> float:
        has_non_ascii = any(ord(ch) > 127 for ch in query)
        if not has_non_ascii:
            return 1.0
        haystack = result.title + " " + result.description
        return 1.0 if any(ord(ch) > 127 for ch in haystack) else 0.0

    def _completeness(self, result: SearchResult) -> float:
        description = (result.description or "").strip()
        length = len(description)
        if not description:
            return 0.0
        if length < 60:
            return 0.4
        if length < 200:
            return 0.8
        return 1.0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return set(token for token in _TOKEN_SPLIT.split((text or "").lower()) if token)

    @staticmethod
    def _normalize_title(title: str) -> str:
        stripped = re.sub(r"[^\w\s]", " ", (title or "").strip().lower())
        return re.sub(r"\s+", " ", stripped).strip()

    @staticmethod
    def confidence_label(score: float) -> SearchConfidence:
        """Coarse confidence label for a single score (used by tests)."""
        if score >= 6.0:
            return SearchConfidence.HIGH
        if score >= 3.0:
            return SearchConfidence.MEDIUM
        return SearchConfidence.LOW
