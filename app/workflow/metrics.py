from __future__ import annotations

from pydantic import BaseModel, Field


class WorkflowMetricsSnapshot(BaseModel):
    """Read-only snapshot of workflow metrics."""

    executions: int = 0
    successes: int = 0
    failures: int = 0
    average_duration_ms: float = 0.0


class WorkflowMetricsCollector:
    """Deterministic in-memory metrics for WorkflowEngine."""

    def __init__(self) -> None:
        self._executions = 0
        self._successes = 0
        self._failures = 0
        self._total_duration_ms = 0.0

    def record_execution(self, success: bool, duration_ms: float) -> None:
        self._executions += 1
        if success:
            self._successes += 1
        else:
            self._failures += 1
        self._total_duration_ms += duration_ms

    def get_metrics(self) -> WorkflowMetricsSnapshot:
        average = 0.0
        if self._executions > 0:
            average = self._total_duration_ms / self._executions

        return WorkflowMetricsSnapshot(
            executions=self._executions,
            successes=self._successes,
            failures=self._failures,
            average_duration_ms=average,
        )
