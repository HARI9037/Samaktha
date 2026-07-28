"""Multimodal metrics for Samaktha Runtime.

Tracks image, audio, document, and video processing requests with
per-type counters, failure tracking, and latency aggregation.
Integrates with the existing telemetry pattern used across Phase 4.6.
"""
from __future__ import annotations

from app.core.contracts.multimodal import MediaType


class MultimodalMetricsCollector:
    """Deterministic, in-memory metrics for multimodal execution."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {
            MediaType.IMAGE.value: 0,
            MediaType.AUDIO.value: 0,
            MediaType.DOCUMENT.value: 0,
            MediaType.VIDEO.value: 0,
        }
        self._failures: dict[str, int] = {
            MediaType.IMAGE.value: 0,
            MediaType.AUDIO.value: 0,
            MediaType.DOCUMENT.value: 0,
            MediaType.VIDEO.value: 0,
        }
        self._latency_totals: dict[str, float] = {
            MediaType.IMAGE.value: 0.0,
            MediaType.AUDIO.value: 0.0,
            MediaType.DOCUMENT.value: 0.0,
            MediaType.VIDEO.value: 0.0,
        }
        self._provider_latency: dict[str, list[float]] = {}

    def record(
        self,
        media_type: MediaType,
        provider_id: str,
        latency_ms: float,
        failed: bool = False,
    ) -> None:
        key = media_type.value
        self._counts[key] = self._counts.get(key, 0) + 1
        self._latency_totals[key] = self._latency_totals.get(key, 0.0) + latency_ms
        if failed:
            self._failures[key] = self._failures.get(key, 0) + 1

        if provider_id not in self._provider_latency:
            self._provider_latency[provider_id] = []
        self._provider_latency[provider_id].append(latency_ms)

    def average_latency(self, media_type: MediaType) -> float:
        key = media_type.value
        count = self._counts.get(key, 0)
        total = self._latency_totals.get(key, 0.0)
        return total / count if count > 0 else 0.0

    def average_provider_latency(self, provider_id: str) -> float:
        latencies = self._provider_latency.get(provider_id, [])
        return sum(latencies) / len(latencies) if latencies else 0.0

    def get_snapshot(self) -> dict:
        return {
            "counts": dict(self._counts),
            "failures": dict(self._failures),
            "latency_totals_ms": dict(self._latency_totals),
            "average_latencies_ms": {
                k: (self._latency_totals[k] / self._counts[k] if self._counts[k] else 0.0)
                for k in self._counts
            },
        }
