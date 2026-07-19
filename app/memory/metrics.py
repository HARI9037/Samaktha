from __future__ import annotations

from pydantic import BaseModel


class MemoryMetricsSnapshot(BaseModel):
    """Read-only snapshot of memory operation metrics."""

    reads: int = 0
    writes: int = 0
    deletes: int = 0
    searches: int = 0

    @property
    def total_operations(self) -> int:
        return self.reads + self.writes + self.deletes + self.searches


class MemoryMetricsCollector:
    """Deterministic in-memory metrics for MemoryManager."""

    def __init__(self) -> None:
        self._reads = 0
        self._writes = 0
        self._deletes = 0
        self._searches = 0

    def record_read(self) -> None:
        self._reads += 1

    def record_write(self) -> None:
        self._writes += 1

    def record_delete(self) -> None:
        self._deletes += 1

    def record_search(self) -> None:
        self._searches += 1

    def get_metrics(self) -> MemoryMetricsSnapshot:
        return MemoryMetricsSnapshot(
            reads=self._reads,
            writes=self._writes,
            deletes=self._deletes,
            searches=self._searches,
        )
