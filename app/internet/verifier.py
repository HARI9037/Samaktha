"""Phase 12.7 — deterministic multi-source verification.

After ranking, the verifier answers one question: how certain is the pipeline
that the top results describe the same truth? It clusters results by
normalized title, measures agreement across independent domains, weights the
cluster by domain authority, and assigns a per-result confidence label. It
never fabricates certainty: no results → UNKNOWN, conflicting sources → LOW.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from app.internet.models import (
    SearchConfidence,
    SearchResponse,
    SearchResult,
    VerificationReport,
)
from app.internet.policy import SearchPolicy

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


class SearchVerifier:
    """Deterministic cross-source agreement/contradiction analyzer."""

    def __init__(self, policy: SearchPolicy | None = None) -> None:
        self._policy = policy or SearchPolicy()

    def verify(self, response: SearchResponse) -> VerificationReport:
        """Analyze a (post-ranking) SearchResponse and return a report.

        Also stamps each result with a confidence label in a copy of the
        response (returned via ``apply``), so the pipeline sees both.
        """
        results = [r for r in response.results if r.url]
        if not results:
            return VerificationReport(
                verdict=SearchConfidence.UNKNOWN,
                notes=["No results to verify."],
            )

        clusters: dict[str, list[SearchResult]] = {}
        for result in results:
            key = self._cluster_key(result)
            clusters.setdefault(key, []).append(result)

        dominant_key = max(
            clusters,
            key=lambda k: sum(self._authority(r) for r in clusters[k]),
        )
        dominant = clusters[dominant_key]
        agreeing = len({r.domain.lower() for r in dominant})
        conflicting = max(0, len(results) - len(dominant))

        verdict, notes = self._verdict(
            results=results,
            dominant=dominant,
            agreeing=agreeing,
            conflicting=conflicting,
        )

        per_result: dict[str, SearchConfidence] = {}
        for result in results:
            in_dominant = self._cluster_key(result) == dominant_key
            per_result[result.url] = self._label(
                result, in_dominant=in_dominant, agreeing=agreeing
            )

        return VerificationReport(
            verdict=verdict,
            per_result=per_result,
            notes=notes,
            agreeing_sources=agreeing,
            conflicting_sources=conflicting,
        )

    def apply(
        self, response: SearchResponse, report: VerificationReport
    ) -> SearchResponse:
        """Return a copy of ``response`` with confidence stamped per result."""
        stamped = [
            result.model_copy(
                update={
                    "confidence": report.per_result.get(
                        result.url, SearchConfidence.UNKNOWN
                    )
                }
            )
            for result in response.results
        ]
        return response.model_copy(update={"results": stamped})

    # ------------------------------------------------------------------
    # Verdict heuristics (all deterministic)
    # ------------------------------------------------------------------

    def _verdict(
        self,
        results: list[SearchResult],
        dominant: list[SearchResult],
        agreeing: int,
        conflicting: int,
    ) -> tuple[SearchConfidence, list[str]]:
        notes: list[str] = []
        if not results:
            return SearchConfidence.UNKNOWN, ["No results available."]

        dominance_ratio = len(dominant) / len(results)
        authority = max(self._authority(r) for r in dominant)

        if len(results) == 1:
            notes.append("Only a single source supports this claim.")
            return SearchConfidence.LOW, notes

        if agreeing >= 2 and dominance_ratio >= 0.6 and authority >= 0.7:
            notes.append(
                f"{agreeing} independent sources agree on the dominant claim."
            )
            if self._all_fresh(dominant):
                return SearchConfidence.HIGH, notes
            notes.append("Agreement found, but several sources are not current.")
            return SearchConfidence.MEDIUM, notes

        if conflicting > 0:
            notes.append(
                f"Sources conflict: {conflicting} result(s) disagree with the "
                "dominant claim."
            )
            return SearchConfidence.LOW, notes

        if agreeing >= 1 and dominance_ratio >= 0.5:
            notes.append(
                "Partial agreement: at least one strong source supports the "
                "dominant claim."
            )
            return SearchConfidence.MEDIUM, notes

        notes.append("Only a single source supports this claim.")
        return SearchConfidence.LOW, notes

    def _all_fresh(self, results: list[SearchResult]) -> bool:
        for result in results:
            published_at = result.published_at or ""
            match = _DATE_RE.match(published_at)
            if not match:
                continue
            try:
                published = datetime(
                    int(match.group(1)), int(match.group(2)), int(match.group(3)),
                    tzinfo=timezone.utc,
                )
            except ValueError:
                continue
            if (datetime.now(timezone.utc) - published).days > 365:
                return False
        return True

    def _label(
        self,
        result: SearchResult,
        in_dominant: bool,
        agreeing: int,
    ) -> SearchConfidence:
        if not in_dominant:
            return SearchConfidence.LOW
        if agreeing >= 2 and self._authority(result) >= 0.7:
            return SearchConfidence.HIGH
        return SearchConfidence.MEDIUM

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cluster_key(result: SearchResult) -> str:
        return re.sub(r"\s+", " ", (result.title or "").strip().lower())[:120]

    def _authority(self, result: SearchResult) -> float:
        domain = result.domain.lower()
        root = domain.split(".")[-2:] if domain.count(".") >= 1 else [domain]
        suffix = ".".join(root)
        if domain in self._policy.authoritative_domains or suffix in {
            ".gov", ".edu", ".org"
        }:
            return 1.0
        return 0.5
