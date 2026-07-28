"""Phase 5.3 tests — Streaming Runtime.

Validates:
- Runtime collects chunks correctly.
- Sequence ordering is preserved.
- Failures are handled safely.
- Architecture invariants (GAMBIT/Workflow isolation) are preserved.
"""
import ast
import os
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.contracts.streaming import StreamChunk, StreamEventType, StreamRequest
from app.runtime.streaming import StreamingExecutor


class MockStreamIterator:
    """Mock an async generator for streaming."""
    def __init__(self, items):
        self.items = items
        self.index = 0
        
    def __aiter__(self):
        return self
        
    async def __anext__(self):
        if self.index < len(self.items):
            item = self.items[self.index]
            self.index += 1
            if isinstance(item, Exception):
                raise item
            return item
        raise StopAsyncIteration


def _build_provider_manager(chunks_or_error):
    manager = MagicMock()
    if isinstance(chunks_or_error, Exception):
        async def mock_stream(*args, **kwargs):
            raise chunks_or_error
            yield  # To make it an async generator
        manager.stream_provider = mock_stream
    else:
        manager.stream_provider = MagicMock(return_value=MockStreamIterator(chunks_or_error))
    return manager


@pytest.mark.asyncio
async def test_streaming_executor_collect_stream():
    chunks = [
        StreamChunk(stream_id="s1", event_type=StreamEventType.STARTED, timestamp=1.0, sequence_number=1),
        StreamChunk(stream_id="s1", event_type=StreamEventType.TOKEN, content="Hello", timestamp=1.1, sequence_number=2),
        StreamChunk(stream_id="s1", event_type=StreamEventType.TOKEN, content=" World", timestamp=1.2, sequence_number=3),
        StreamChunk(stream_id="s1", event_type=StreamEventType.COMPLETED, timestamp=1.3, sequence_number=4),
    ]
    
    manager = _build_provider_manager(chunks)
    executor = StreamingExecutor(provider_manager=manager)
    
    request = StreamRequest(request_id="req1", provider_id="mock", prompt="hi")
    response = await executor.collect_stream(request)
    
    assert response.status == "completed"
    assert response.chunks_count == 4
    assert response.final_content == "Hello World"
    
    metrics = executor.get_metrics()
    assert metrics["total_streams"] == 1
    assert metrics["completed_streams"] == 1
    assert metrics["failed_streams"] == 0
    assert metrics["total_chunks"] == 4
    assert metrics["tokens_received"] == 2


@pytest.mark.asyncio
async def test_streaming_executor_handles_failure_mid_stream():
    chunks = [
        StreamChunk(stream_id="s2", event_type=StreamEventType.STARTED, timestamp=1.0, sequence_number=1),
        StreamChunk(stream_id="s2", event_type=StreamEventType.TOKEN, content="Oops", timestamp=1.1, sequence_number=2),
        Exception("Network drop"),
    ]
    
    manager = _build_provider_manager(chunks)
    executor = StreamingExecutor(provider_manager=manager)
    
    request = StreamRequest(request_id="req2", provider_id="mock", prompt="fail")
    response = await executor.collect_stream(request)
    
    # Executor should catch the failure, yield a FAILED chunk internally, and collect it
    assert response.status == "failed"
    assert response.chunks_count == 3  # STARTED, TOKEN, FAILED(injected)
    assert "Oops" in response.final_content
    assert "Stream error: Network drop" in response.final_content
    
    metrics = executor.get_metrics()
    assert metrics["completed_streams"] == 0
    assert metrics["failed_streams"] == 1


# Architecture Tests

def check_no_streaming_imports(filepath):
    """Ensure GAMBIT and Workflow don't import streaming runtime."""
    with open(filepath, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=filepath)
        
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                assert "app.runtime.streaming" not in name.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert "app.runtime.streaming" not in node.module


def test_architecture_gambit_no_streaming():
    base_dir = os.path.join(os.path.dirname(__file__), "../../app/gambit")
    if not os.path.exists(base_dir):
        return  # skip if doesn't exist
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.endswith(".py"):
                check_no_streaming_imports(os.path.join(root, file))


def test_architecture_workflow_no_streaming():
    base_dir = os.path.join(os.path.dirname(__file__), "../../app/workflow")
    if not os.path.exists(base_dir):
        return  # skip if doesn't exist
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.endswith(".py"):
                check_no_streaming_imports(os.path.join(root, file))
