"""Phase 8 — Memory Ranker.

Multi-signal scoring for memory items.

Score combines:
    - Semantic similarity (from SemanticIndex or future vector engine)
    - Importance (from MetadataManager)
    - Recency (how recently created/accessed)
    - Frequency (how often accessed)
    - Confidence (how reliable the memory is)
    - User preference signal
    - Access history

All signals are normalised to [0, 1] and combined with configured weights.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Default weights — can be overridden at construction
# ---------------------------------------------------------------------------

_DEFAULT_WEIGHTS = {
    "semantic": 0.40,
    "recency": 0.25,
    "importance": 0.20,
    "confidence": 0.10,
    "frequency": 0.05,
}

# ---------------------------------------------------------------------------
# Recency decay
# ---------------------------------------------------------------------------

_HALF_LIFE_DAYS = 7.0  # score halves after this many days


def _recency_score(created_at_iso: str | None) -> float:
    """Score based on how recent the memory is (exponential decay)."""
    if not created_at_iso:
        return 0.0
    try:
        created = datetime.fromisoformat(created_at_iso)
        now = datetime.utcnow()
        age_days = (now - created).total_seconds() / 86400.0
        return max(0.0, 2.0 ** (-age_days / _HALF_LIFE_DAYS))
    except (ValueError, TypeError):
        return 0.0


def _frequency_score(access_counter: int) -> float:
    """Normalise access count to [0, 1] with diminishing returns."""
    if access_counter <= 0:
        return 0.0
    return min(1.0, access_counter / 50.0)


def _confidence_score(confidence: float) -> float:
    """Confidence is already in [0, 1]."""
    return max(0.0, min(1.0, confidence))


class MemoryRanker:
    """Multi-signal ranker for memory items.

    Expects items with a ``.metadata`` dict (or indexable by key) containing
    standard MetadataManager fields.
    """

    def __init__(self, weights: dict[str, float] | None = None):
        self._weights = {**_DEFAULT_WEIGHTS, **(weights or {})}

    def score(self, item: Any, semantic_score: float = 0.0) -> float:
        """Compute a combined relevance score for a single memory item.

        Formula:
            0.40 semantic + 0.25 recency + 0.20 importance
            + 0.10 confidence + 0.05 access frequency

        Parameters
        ----------
        item:
            Object with ``.metadata`` dict containing standard
            MetadataManager fields.
        semantic_score:
            Pre-computed semantic similarity score [0, 1].

        Returns
        -------
        float in [0, 1]
        """
        meta = self._extract_metadata(item)

        w = self._weights

        sem = min(max(semantic_score, 0.0), 1.0) * w["semantic"]
        rec = _recency_score(meta.get("created_at")) * w["recency"]
        imp = meta.get("importance", 0.3) * w["importance"]
        conf = _confidence_score(float(meta.get("confidence", 1.0))) * w["confidence"]
        freq = _frequency_score(int(meta.get("access_counter", 0))) * w["frequency"]

        return round(sem + rec + imp + conf + freq, 6)

    def rank(
        self,
        items: list[Any],
        semantic_scores: dict[str, float] | None = None,
    ) -> list[tuple[Any, float]]:
        """Rank a list of items by combined score, descending.

        Returns list of (item, score) tuples sorted by score descending.
        """
        scored: list[tuple[Any, float]] = []
        for item in items:
            item_id = self._get_id(item)
            sem = (semantic_scores or {}).get(item_id, 0.0)
            s = self.score(item, sem)
            scored.append((item, s))
        scored.sort(key=lambda x: (-x[1], self._get_id(x[0])))
        return scored

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_metadata(item: Any) -> dict[str, Any]:
        if hasattr(item, "metadata") and isinstance(item.metadata, dict):
            return item.metadata
        if isinstance(item, dict):
            return item.get("metadata", {})
        return {}

    @staticmethod
    def _get_id(item: Any) -> str:
        if hasattr(item, "id"):
            return str(item.id)
        if hasattr(item, "memory_id"):
            return str(item.memory_id)
        if isinstance(item, dict):
            return str(item.get("id", ""))
        return ""
