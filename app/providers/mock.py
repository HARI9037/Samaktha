from __future__ import annotations

from typing import Any, AsyncIterator
import asyncio
import os
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
        if os.environ.get("SAMAKTHA_INTERNAL_VALIDATION") == "1":
            try:
                delay = min(
                    60.0,
                    max(0.0, float(os.environ.get("SAMAKTHA_INTERNAL_MOCK_DELAY_SECONDS", "0"))),
                )
            except ValueError:
                delay = 0.0
            if delay:
                await asyncio.sleep(delay)
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
