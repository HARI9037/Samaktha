"""Phase 12.1/12.3 — InternetTool governance + safety policy.

SearchPolicy is the single deterministic gatekeeper for internet access: how
many results are allowed, which categories may be used, whether CAP approval
is mandatory, how long results may be cached, and how much content may be
fetched. No provider call may bypass this policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SearchPolicy:
    """Immutable ruleset governing every internet-intelligence request."""

    enabled: bool = True
    """Master switch: when False every internet request is refused."""

    require_approval: bool = True
    """When True the InternetTool refuses to run without a CAP permit."""

    max_results: int = 5
    """Maximum number of ranked results returned to the pipeline."""

    max_content_chars: int = 12_000
    """Cap on fetched content injected into the LLM context."""

    max_query_length: int = 200
    """Cap on query length — refuse absurdly long inputs."""

    allow_fetch: bool = True
    """Whether the content-fetch action is permitted at all."""

    allow_suggestions: bool = True
    """Whether the suggestions action is permitted."""

    ttl_seconds: int = 300
    """Default cache TTL for general web results."""

    news_ttl_seconds: int = 60
    """Cache TTL for news results (more volatile)."""

    category_allowlist: tuple[str, ...] = ("web", "news")
    """Categories the pipeline may request from a provider."""

    supported_actions: tuple[str, ...] = ("search", "news", "fetch", "suggest")
    """Actions the InternetTool facade understands."""

    authoritative_domains: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "wikipedia.org",
                "docs.python.org",
                "developer.mozilla.org",
                "github.com",
                "stackoverflow.com",
                "arxiv.org",
                "scholar.google.com",
                "who.int",
                "cdc.gov",
                "nasa.gov",
                "ieee.org",
                "acm.org",
                "oecd.org",
                "un.org",
            }
        )
    )
    """High-authority domains that weight the ranking/verification pass."""

    def ttl_for(self, category: str) -> int:
        """Return the configured TTL for the given search category."""
        if category == "news":
            return self.news_ttl_seconds
        return self.ttl_seconds

    def allows_category(self, category: str) -> bool:
        return category in self.category_allowlist

    def allows_action(self, action: str) -> bool:
        return action in self.supported_actions
