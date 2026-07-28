"""Tool Chain metrics for Samaktha Runtime.

Tracks ToolChain lifecycle metrics: started, completed, failed, total steps, and average chain duration.
Integrates with the Phase 4.6 telemetry pattern.
"""
from __future__ import annotations


class ToolChainMetricsCollector:
    """Deterministic, in-memory metrics for tool chain execution."""

    def __init__(self) -> None:
        self.chains_started: int = 0
        self.chains_completed: int = 0
        self.chains_failed: int = 0
        self.total_steps: int = 0
        self.failed_steps: int = 0
        self.retry_count: int = 0
        
        # Cumulative tracking for averages
        self._total_chain_duration_ms: float = 0.0

    def record_chain_started(self) -> None:
        self.chains_started += 1

    def record_step_execution(self, success: bool) -> None:
        self.total_steps += 1
        if not success:
            self.failed_steps += 1

    def record_retry(self) -> None:
        self.retry_count += 1

    def record_chain_completed(self, duration_ms: float) -> None:
        self.chains_completed += 1
        self._total_chain_duration_ms += duration_ms

    def record_chain_failed(self, duration_ms: float) -> None:
        self.chains_failed += 1
        self._total_chain_duration_ms += duration_ms

    @property
    def average_chain_duration(self) -> float:
        total_finished = self.chains_completed + self.chains_failed
        if total_finished == 0:
            return 0.0
        return self._total_chain_duration_ms / total_finished

    def get_snapshot(self) -> dict:
        return {
            "chains_started": self.chains_started,
            "chains_completed": self.chains_completed,
            "chains_failed": self.chains_failed,
            "total_steps": self.total_steps,
            "failed_steps": self.failed_steps,
            "retry_count": self.retry_count,
            "average_chain_duration_ms": self.average_chain_duration,
        }
