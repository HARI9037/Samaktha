from __future__ import annotations

from pydantic import BaseModel


class RouterMetricsSnapshot(BaseModel):
    """Read-only snapshot of router metrics."""

    decisions: int = 0
    successful_decisions: int = 0
    failed_decisions: int = 0


class RouterMetricsCollector:
    """Deterministic in-memory metrics for ModelRouter."""

    def __init__(self) -> None:
        self._decisions = 0
        self._successful_decisions = 0
        self._failed_decisions = 0

    def record_decision(self, *, successful: bool) -> None:
        self._decisions += 1
        if successful:
            self._successful_decisions += 1
        else:
            self._failed_decisions += 1

    def get_metrics(self) -> RouterMetricsSnapshot:
        return RouterMetricsSnapshot(
            decisions=self._decisions,
            successful_decisions=self._successful_decisions,
            failed_decisions=self._failed_decisions,
        )
