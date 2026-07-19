from __future__ import annotations

from pydantic import BaseModel


class OrchestratorMetricsSnapshot(BaseModel):
    """Read-only snapshot of orchestrator pipeline metrics."""

    pipelines: int = 0
    successes: int = 0
    failures: int = 0
    governance_blocks: int = 0


class OrchestratorMetricsCollector:
    """Deterministic in-memory metrics for SamakthaOrchestrator."""

    def __init__(self) -> None:
        self._pipelines = 0
        self._successes = 0
        self._failures = 0
        self._governance_blocks = 0

    def record_pipeline(self, *, success: bool, governance_blocked: bool = False) -> None:
        self._pipelines += 1
        if governance_blocked:
            self._governance_blocks += 1
            self._failures += 1
        elif success:
            self._successes += 1
        else:
            self._failures += 1

    def get_metrics(self) -> OrchestratorMetricsSnapshot:
        return OrchestratorMetricsSnapshot(
            pipelines=self._pipelines,
            successes=self._successes,
            failures=self._failures,
            governance_blocks=self._governance_blocks,
        )
