"""Phase 5.3 tests — Streaming Contracts."""
import time

from app.core.contracts.streaming import (
    StreamChunk,
    StreamEventType,
    StreamRequest,
    StreamResponse,
)


def test_stream_event_type_enum():
    assert StreamEventType.STARTED == "started"
    assert StreamEventType.TOKEN == "token"
    assert StreamEventType.PARTIAL_RESULT == "partial_result"
    assert StreamEventType.COMPLETED == "completed"
    assert StreamEventType.FAILED == "failed"
    assert StreamEventType.HEARTBEAT == "heartbeat"


def test_stream_chunk_serialization():
    chunk = StreamChunk(
        stream_id="s123",
        event_type=StreamEventType.TOKEN,
        content="hello",
        timestamp=12345.6,
        sequence_number=1,
    )
    data = chunk.model_dump()
    assert data["stream_id"] == "s123"
    assert data["event_type"] == "token"
    assert data["content"] == "hello"
    assert data["timestamp"] == 12345.6
    assert data["sequence_number"] == 1
    assert data["metadata"] == {}


def test_stream_request_defaults():
    req = StreamRequest(
        request_id="req1",
        provider_id="mock",
        prompt="say hi",
    )
    assert req.capabilities == []
    assert req.metadata == {}


def test_stream_response_serialization():
    res = StreamResponse(
        stream_id="s123",
        status="completed",
        chunks_count=10,
        final_content="hello world",
        duration_ms=45.0,
    )
    data = res.model_dump()
    assert data["stream_id"] == "s123"
    assert data["status"] == "completed"
    assert data["chunks_count"] == 10
    assert data["final_content"] == "hello world"
    assert data["duration_ms"] == 45.0
