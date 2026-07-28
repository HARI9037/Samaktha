from __future__ import annotations

from pydantic import BaseModel


class RuntimeMetricsSnapshot(BaseModel):
    """Read-only snapshot of runtime metrics."""

    dispatch_count: int = 0
    batch_executions: int = 0
    concurrent_dispatches: int = 0
    average_batch_duration: float = 0.0


class RuntimeMetricsCollector:
    """Deterministic in-memory metrics for Runtime Engine."""

    def __init__(self) -> None:
        self._dispatch_count = 0
        self._batch_executions = 0
        self._concurrent_dispatches = 0
        self._total_batch_duration_ms = 0.0

    def record_dispatch(self) -> None:
        self._dispatch_count += 1

    def record_batch_execution(self, task_count: int, duration_ms: float) -> None:
        self._batch_executions += 1
        self._concurrent_dispatches += task_count
        self._total_batch_duration_ms += duration_ms

    def get_metrics(self) -> RuntimeMetricsSnapshot:
        average_batch = 0.0
        if self._batch_executions > 0:
            average_batch = self._total_batch_duration_ms / self._batch_executions
        return RuntimeMetricsSnapshot(
            dispatch_count=self._dispatch_count,
            batch_executions=self._batch_executions,
            concurrent_dispatches=self._concurrent_dispatches,
            average_batch_duration=average_batch,
        )
