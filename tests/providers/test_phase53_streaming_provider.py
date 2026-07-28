"""Phase 5.3 tests — Streaming Provider.

Validates:
- MockProvider emits ordered chunks.
- Unsupported provider fails correctly.
- Stream completion works properly.
"""
import pytest

from app.core.contracts.streaming import StreamEventType, StreamRequest
from app.providers.base import BaseProvider
from app.providers.mock import MockProvider


class UnsupportedProvider(BaseProvider):
    @property
    def name(self):
        return "unsupported"

    async def execute(self, payload):
        return {}

    def supports(self, capability):
        return True

    async def health_check(self):
        return True
        
    # No stream() method defined, falls back to BaseProvider default


@pytest.mark.asyncio
async def test_mock_provider_emits_ordered_chunks():
    provider = MockProvider()
    request = StreamRequest(request_id="req1", provider_id="mock", prompt="test")
    
    chunks = [chunk async for chunk in provider.stream(request)]
    
    assert len(chunks) == 4
    
    # Verify sequence order
    assert chunks[0].sequence_number == 1
    assert chunks[1].sequence_number == 2
    assert chunks[2].sequence_number == 3
    assert chunks[3].sequence_number == 4
    
    # Verify event types
    assert chunks[0].event_type == StreamEventType.STARTED
    assert chunks[1].event_type == StreamEventType.TOKEN
    assert chunks[2].event_type == StreamEventType.TOKEN
    assert chunks[3].event_type == StreamEventType.COMPLETED
    
    # Verify content concatenation
    full_content = "".join(c.content for c in chunks if c.event_type == StreamEventType.TOKEN)
    assert full_content == "Mock stream"


@pytest.mark.asyncio
async def test_unsupported_provider_fails_correctly():
    provider = UnsupportedProvider()
    request = StreamRequest(request_id="req2", provider_id="unsupported", prompt="test")
    
    with pytest.raises(NotImplementedError, match="does not support streaming via StreamRequest"):
        # The generator raises the error as soon as it is evaluated
        async for _ in provider.stream(request):
            pass
