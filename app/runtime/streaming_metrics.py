"""Streaming metrics for Samaktha Runtime.

Tracks streaming lifecycle metrics: started, completed, failed, latency, and tokens.
Integrates with the Phase 4.6 telemetry pattern.
"""
from __future__ import annotations


class StreamingMetricsCollector:
    """Deterministic, in-memory metrics for streaming execution."""

    def __init__(self) -> None:
        self.total_streams: int = 0
        self.completed_streams: int = 0
        self.failed_streams: int = 0
        self.total_chunks: int = 0
        self.tokens_received: int = 0
        
        # Cumulative tracking for averages
        self._total_first_token_latency_ms: float = 0.0
        self._total_stream_duration_ms: float = 0.0

    def record_stream_started(self) -> None:
        self.total_streams += 1

    def record_first_token(self, latency_ms: float) -> None:
        self._total_first_token_latency_ms += latency_ms

    def record_chunk(self, is_token: bool = True) -> None:
        self.total_chunks += 1
        if is_token:
            self.tokens_received += 1

    def record_stream_completed(self, duration_ms: float) -> None:
        self.completed_streams += 1
        self._total_stream_duration_ms += duration_ms

    def record_stream_failed(self) -> None:
        self.failed_streams += 1

    @property
    def average_first_token_latency(self) -> float:
        if self.completed_streams == 0 and self.failed_streams == 0:
            return 0.0
        # First token usually arrives for both completed and failed, 
        # approximate count as total_streams that started sending
        count = self.completed_streams + self.failed_streams
        return self._total_first_token_latency_ms / count if count > 0 else 0.0

    @property
    def average_stream_duration(self) -> float:
        if self.completed_streams == 0:
            return 0.0
        return self._total_stream_duration_ms / self.completed_streams

    def get_snapshot(self) -> dict:
        return {
            "total_streams": self.total_streams,
            "completed_streams": self.completed_streams,
            "failed_streams": self.failed_streams,
            "total_chunks": self.total_chunks,
            "tokens_received": self.tokens_received,
            "average_first_token_latency_ms": self.average_first_token_latency,
            "average_stream_duration_ms": self.average_stream_duration,
        }
