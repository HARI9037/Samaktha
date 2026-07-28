from __future__ import annotations

from typing import Any, Protocol

from app.core.contracts.telemetry import TelemetrySnapshot


class TelemetryCollector(Protocol):
    """Protocol for telemetry collectors."""

    def get_metrics(self) -> TelemetrySnapshot:
        ...


class TelemetryRegistry:
    """Central registry for telemetry collectors without external dependencies."""

    def __init__(self) -> None:
        self._collectors: dict[str, TelemetryCollector] = {}

    def register(self, name: str, collector: TelemetryCollector) -> None:
        """Register a new collector."""
        self._collectors[name] = collector

    def get_aggregated_snapshot(self) -> TelemetrySnapshot:
        """Aggregate metrics from all registered collectors."""
        aggregated: dict[str, Any] = {}
        for name, collector in self._collectors.items():
            snapshot = collector.get_metrics()
            aggregated[name] = snapshot.metrics

        return TelemetrySnapshot(metrics=aggregated)
