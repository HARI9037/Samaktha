"""Phase 4.3 — Worker Metrics.

Observability for the distributed worker layer.
"""

from __future__ import annotations

from pydantic import BaseModel


class WorkerMetricsSnapshot(BaseModel):
    """Read-only snapshot of worker execution metrics."""

    worker_registrations: int = 0
    task_assignments: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    worker_switches: int = 0


class WorkerMetricsCollector:
    """Deterministic in-memory metrics for Worker assignments."""

    def __init__(self) -> None:
        self._registrations = 0
        self._assignments = 0
        self._successes = 0
        self._failures = 0
        self._switches = 0

    def record_registration(self) -> None:
        self._registrations += 1

    def record_assignment(self) -> None:
        self._assignments += 1

    def record_success(self) -> None:
        self._successes += 1

    def record_failure(self) -> None:
        self._failures += 1

    def record_switch(self) -> None:
        self._switches += 1

    def get_metrics(self) -> WorkerMetricsSnapshot:
        return WorkerMetricsSnapshot(
            worker_registrations=self._registrations,
            task_assignments=self._assignments,
            successful_executions=self._successes,
            failed_executions=self._failures,
            worker_switches=self._switches,
        )
