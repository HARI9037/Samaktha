"""P1.5 — HTTP observability metrics.

A small in-memory collector for the HTTP execution layer plus an adapter that
exposes existing ``get_snapshot``-style collectors through the
``TelemetryCollector`` protocol so the aggregated ``/metrics`` endpoint can
report security, streaming, and HTTP counters together.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request

from app.core.contracts.telemetry import TelemetrySnapshot

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics_endpoint(request: Request) -> dict:
    """Aggregated telemetry snapshot from all registered collectors."""
    registry = getattr(request.app.state, "telemetry", None)
    if registry is None:
        return {"metrics": {}}
    return registry.get_aggregated_snapshot().model_dump()


class HttpMetricsCollector:
    """Deterministic counters for the HTTP execution layer."""

    def __init__(self) -> None:
        self.requests: int = 0
        self.completed: int = 0
        self.failed: int = 0
        self.timeouts: int = 0
        self.rate_limited: int = 0
        self.request_too_large: int = 0
        self.cancelled: int = 0
        self._durations: list[float] = []
        self._max_durations = 500

    def record_request(self) -> None:
        self.requests += 1

    def record_completed(self, duration_s: float) -> None:
        self.completed += 1
        self._durations.append(duration_s)
        if len(self._durations) > self._max_durations:
            self._durations = self._durations[-self._max_durations:]

    def record_failed(self) -> None:
        self.failed += 1

    def record_timeout(self) -> None:
        self.timeouts += 1

    def record_rate_limited(self) -> None:
        self.rate_limited += 1

    def record_request_too_large(self) -> None:
        self.request_too_large += 1

    def record_cancelled(self) -> None:
        self.cancelled += 1

    def get_metrics(self) -> TelemetrySnapshot:
        durations = self._durations
        average_ms = (sum(durations) / len(durations)) * 1000 if durations else 0.0
        last_ms = durations[-1] * 1000 if durations else 0.0
        return TelemetrySnapshot(
            metrics={
                "requests": self.requests,
                "completed": self.completed,
                "failed": self.failed,
                "timeouts": self.timeouts,
                "rate_limited": self.rate_limited,
                "request_too_large": self.request_too_large,
                "cancelled": self.cancelled,
                "average_duration_ms": average_ms,
                "last_duration_ms": last_ms,
            }
        )


def snapshot_adapter(collector: Any) -> Any:
    """Adapt a snapshot/metrics-style collector to the telemetry protocol.

    Accepts any object exposing ``get_snapshot()`` or ``get_metrics()`` (each
    returning a dict or a pydantic model) or a zero-argument callable that
    yields the raw snapshot. Pydantic models are dumped to plain dicts so the
    aggregated ``/metrics`` shape stays flat and JSON-serializable.
    """

    class _Adapter:
        def get_metrics(self) -> TelemetrySnapshot:
            target = collector
            if (
                callable(target)
                and not hasattr(target, "get_snapshot")
                and not hasattr(target, "get_metrics")
            ):
                raw = target()
            else:
                get_snapshot = getattr(target, "get_snapshot", None)
                get_metrics = getattr(target, "get_metrics", None)
                if callable(get_snapshot):
                    raw = get_snapshot()
                elif callable(get_metrics):
                    raw = get_metrics()
                else:
                    raw = {}
            if raw is None:
                raw = {}
            if hasattr(raw, "model_dump"):
                raw = raw.model_dump()
            if not isinstance(raw, dict):
                raw = {"value": raw}
            return TelemetrySnapshot(metrics=raw)

    return _Adapter()


def provider_metrics_adapter(provider_manager: Any) -> Any:
    """Adapt a provider manager's per-provider statistics to the protocol.

    Exposes ``list_provider_metrics()`` (or ``ProviderMetricsStore.all()``)
    as a ``providers`` key mapping each provider id to its metrics dict.
    """

    class _Adapter:
        def get_metrics(self) -> TelemetrySnapshot:
            records = []
            list_metrics = getattr(provider_manager, "list_provider_metrics", None)
            if callable(list_metrics):
                records = list_metrics() or []
            else:
                store = getattr(provider_manager, "_metrics", None)
                if store is not None and hasattr(store, "all"):
                    records = store.all() or []
            return TelemetrySnapshot(
                metrics={
                    "providers": {
                        record.provider_id: record.model_dump() if hasattr(record, "model_dump") else record
                        for record in records
                    }
                }
            )

    return _Adapter()
