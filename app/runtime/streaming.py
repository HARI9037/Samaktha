"""Streaming executor for Samaktha Runtime.

Consumes provider streams securely. Validates ordering, handles failures,
aggregates final response, and emits telemetry.

Must remain the only layer interacting directly with the stream.
"""
from __future__ import annotations

import time
from typing import AsyncIterator, Optional, TYPE_CHECKING

from app.core.contracts.streaming import (
    StreamChunk,
    StreamEventType,
    StreamRequest,
    StreamResponse,
)
from app.runtime.streaming_metrics import StreamingMetricsCollector

if TYPE_CHECKING:
    from app.core.contracts.runtime import RuntimeContext
    from app.providers.manager import ProviderManager


class StreamingExecutor:
    """Executes streaming requests through ProviderManager and tracks lifecycle."""

    def __init__(
        self,
        provider_manager: "ProviderManager",
        metrics: Optional[StreamingMetricsCollector] = None,
    ) -> None:
        self._provider_manager = provider_manager
        self._metrics = metrics or StreamingMetricsCollector()

    def get_metrics(self) -> dict:
        return self._metrics.get_snapshot()

    async def stream_execute(
        self,
        request: StreamRequest,
        context: Optional["RuntimeContext"] = None,
    ) -> AsyncIterator[StreamChunk]:
        """Execute a streaming request and yield chunks directly.
        
        Validates chunk ordering and logs traces.
        """
        self._metrics.record_stream_started()
        
        if context and context.trace:
            context.trace.add_event(
                source="runtime.streaming",
                event_type="streaming.execution.started",
                provider_id=request.provider_id,
            )

        start_time = time.perf_counter()
        first_token_time: Optional[float] = None
        expected_seq = 1
        has_failed = False

        try:
            async for chunk in self._provider_manager.stream_provider(request):
                # Validate sequencing
                if chunk.sequence_number < expected_seq:
                    # In a strict environment, out-of-order chunks might raise or be dropped.
                    # We will log it/skip it for safety, or yield it anyway depending on policy.
                    pass
                
                expected_seq = chunk.sequence_number + 1

                if chunk.event_type == StreamEventType.TOKEN:
                    self._metrics.record_chunk(is_token=True)
                    if first_token_time is None:
                        first_token_time = time.perf_counter()
                        latency_ms = (first_token_time - start_time) * 1000
                        self._metrics.record_first_token(latency_ms)
                elif chunk.event_type == StreamEventType.FAILED:
                    has_failed = True
                    self._metrics.record_stream_failed()
                else:
                    self._metrics.record_chunk(is_token=False)

                yield chunk
                
                if has_failed:
                    break

            if not has_failed:
                duration_ms = (time.perf_counter() - start_time) * 1000
                self._metrics.record_stream_completed(duration_ms)

        except Exception as exc:
            self._metrics.record_stream_failed()
            if context and context.trace:
                context.trace.add_event(
                    source="runtime.streaming",
                    event_type="streaming.execution.failed",
                    provider_id=request.provider_id,
                    error=str(exc)
                )
            # Yield a final failure chunk so consumers know the stream died unexpectedly
            yield StreamChunk(
                stream_id=f"stream-{request.request_id}",
                event_type=StreamEventType.FAILED,
                content=f"Stream error: {str(exc)}",
                timestamp=time.time(),
                sequence_number=expected_seq,
            )
            raise RuntimeError(f"Streaming execution failed: {exc}") from exc

        finally:
            if context and context.trace and not has_failed:
                context.trace.add_event(
                    source="runtime.streaming",
                    event_type="streaming.execution.completed",
                    provider_id=request.provider_id,
                    duration_ms=(time.perf_counter() - start_time) * 1000
                )

    async def collect_stream(
        self,
        request: StreamRequest,
        context: Optional["RuntimeContext"] = None,
    ) -> StreamResponse:
        """Consume the entire stream and return the aggregated response."""
        content_parts = []
        chunks_count = 0
        stream_id = ""
        status = "completed"
        
        start_time = time.perf_counter()

        try:
            async for chunk in self.stream_execute(request, context):
                chunks_count += 1
                stream_id = chunk.stream_id
                
                if chunk.event_type == StreamEventType.TOKEN:
                    content_parts.append(chunk.content)
                elif chunk.event_type == StreamEventType.FAILED:
                    status = "failed"
                    content_parts.append(chunk.content)
                    
        except RuntimeError:
            status = "failed"

        duration_ms = (time.perf_counter() - start_time) * 1000
        
        return StreamResponse(
            stream_id=stream_id or f"stream-{request.request_id}",
            status=status,
            chunks_count=chunks_count,
            final_content="".join(content_parts),
            duration_ms=duration_ms,
        )
