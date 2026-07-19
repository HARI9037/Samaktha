from __future__ import annotations

from pydantic import BaseModel


class RuntimeMetricsSnapshot(BaseModel):
    """Read-only snapshot of runtime metrics."""

    dispatch_count: int = 0


class RuntimeMetricsCollector:
    """Deterministic in-memory metrics for Runtime Engine."""

    def __init__(self) -> None:
        self._dispatch_count = 0

    def record_dispatch(self) -> None:
        self._dispatch_count += 1

    def get_metrics(self) -> RuntimeMetricsSnapshot:
        return RuntimeMetricsSnapshot(
            dispatch_count=self._dispatch_count,
        )
