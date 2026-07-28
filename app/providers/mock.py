from __future__ import annotations

from typing import Any, AsyncIterator
import time

from app.core.contracts.provider import ProviderCapability
from app.core.contracts.streaming import StreamChunk, StreamEventType, StreamRequest
from app.providers.base import BaseProvider


class MockProvider(BaseProvider):
    """Test provider that returns a deterministic response."""

    @property
    def name(self) -> str:
        return "mock"

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"response": "Mock provider response"}

    def supports(self, capability: ProviderCapability) -> bool:
        return True

    async def health_check(self) -> bool:
        return True

    async def stream(self, request: StreamRequest) -> AsyncIterator[StreamChunk]:
        """Emit a deterministic sequence of chunks for testing."""
        stream_id = f"stream-{request.request_id}"
        
        # 1. Started
        yield StreamChunk(
            stream_id=stream_id,
            event_type=StreamEventType.STARTED,
            content="",
            timestamp=time.time(),
            sequence_number=1,
        )
        
        # 2. Token
        yield StreamChunk(
            stream_id=stream_id,
            event_type=StreamEventType.TOKEN,
            content="Mock ",
            timestamp=time.time(),
            sequence_number=2,
        )
        
        # 3. Token
        yield StreamChunk(
            stream_id=stream_id,
            event_type=StreamEventType.TOKEN,
            content="stream",
            timestamp=time.time(),
            sequence_number=3,
        )
        
        # 4. Completed
        yield StreamChunk(
            stream_id=stream_id,
            event_type=StreamEventType.COMPLETED,
            content="",
            timestamp=time.time(),
            sequence_number=4,
        )
