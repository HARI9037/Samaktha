"""Phase 4.5 — Semantic memory observability."""
from __future__ import annotations

from pydantic import BaseModel


class SemanticMetricsSnapshot(BaseModel):
    searches: int = 0
    retrievals: int = 0
    avg_score: float = 0.0
    cache_hits: int = 0
    failed_retrievals: int = 0


class SemanticMetricsCollector:
    """Tracks semantic index search operations."""

    def __init__(self) -> None:
        self._searches = 0
        self._retrievals = 0
        self._total_score = 0.0
        self._cache_hits = 0
        self._failed_retrievals = 0

    def record_search(self, result_count: int, top_score: float = 0.0) -> None:
        self._searches += 1
        self._retrievals += result_count
        if result_count == 0:
            self._failed_retrievals += 1
        else:
            self._total_score += top_score

    def record_cache_hit(self) -> None:
        self._cache_hits += 1

    def get_metrics(self) -> SemanticMetricsSnapshot:
        successful = self._searches - self._failed_retrievals
        avg = self._total_score / successful if successful > 0 else 0.0
        return SemanticMetricsSnapshot(
            searches=self._searches,
            retrievals=self._retrievals,
            avg_score=round(avg, 4),
            cache_hits=self._cache_hits,
            failed_retrievals=self._failed_retrievals,
        )
