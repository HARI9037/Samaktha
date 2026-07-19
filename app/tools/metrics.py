from __future__ import annotations

from pydantic import BaseModel


class ToolMetricsSnapshot(BaseModel):
    """Read-only snapshot of tool execution metrics."""

    execution_count: int = 0
    failures: int = 0


class ToolMetricsCollector:
    """Deterministic in-memory metrics for ToolManager."""

    def __init__(self) -> None:
        self._execution_count = 0
        self._failures = 0

    def record_execution(self, *, success: bool) -> None:
        self._execution_count += 1
        if not success:
            self._failures += 1

    def get_metrics(self) -> ToolMetricsSnapshot:
        return ToolMetricsSnapshot(
            execution_count=self._execution_count,
            failures=self._failures,
        )
