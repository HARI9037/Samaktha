"""Phase 14.1 — VoiceRuntimeAdapter tests.

Covers:
- RuntimeAdapter translation of provider stream chunks
- Provider stream filtering (only provider tokens yielded)
- Tool event suppression
- Error propagation
- Runtime error surfacing as natural speech
- Streaming order preservation
- No JSON/dict/stringify of runtime dictionaries
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from app.voice.runtime_adapter import VoiceRuntimeAdapter, VoiceRuntimeAdapterV2


# ---------------------------------------------------------------------------
# Helper: async iterable that mimics ProductionAgentRuntime.handle_message
# ---------------------------------------------------------------------------


class AsyncStream:
    """Async iterable that yields dict items, mimicking handle_message output."""

    def __init__(self, items):
        self._items = items

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


async def _collect(stream):
    results = []
    async for item in stream:
        results.append(item)
    return results


# ---------------------------------------------------------------------------
# VoiceRuntimeAdapter
# ---------------------------------------------------------------------------


class TestRuntimeAdapterTranslation:
    def test_adapter_yields_provider_content(self):
        mock_runtime = MagicMock()
        mock_runtime.handle_message = MagicMock(return_value=AsyncStream([
            {"type": "provider", "content": "Hello world"},
            {"type": "provider", "content": " How are you?"},
        ]))

        adapter = VoiceRuntimeAdapter(mock_runtime, session_id="test-session")
        result = asyncio.run(_collect(adapter.stream_response("test input")))

        assert result == ["Hello world", " How are you?"]

    def test_adapter_suppresses_tool_events(self):
        mock_runtime = MagicMock()
        mock_runtime.handle_message = MagicMock(return_value=AsyncStream([
            {"type": "tool", "content": "tool output", "action": "shell"},
            {"type": "provider", "content": "The result is ready"},
        ]))

        adapter = VoiceRuntimeAdapter(mock_runtime, session_id="test-session")
        result = asyncio.run(_collect(adapter.stream_response("test input")))

        assert result == ["The result is ready"]
        assert not any("tool output" in r for r in result)

    def test_adapter_suppresses_internal_events(self):
        mock_runtime = MagicMock()
        mock_runtime.handle_message = MagicMock(return_value=AsyncStream([
            {"type": "status", "content": "processing"},
            {"type": "provider", "content": "Done"},
        ]))

        adapter = VoiceRuntimeAdapter(mock_runtime, session_id="test-session")
        result = asyncio.run(_collect(adapter.stream_response("test input")))

        assert result == ["Done"]

    def test_adapter_speaks_runtime_errors(self):
        mock_runtime = MagicMock()
        mock_runtime.handle_message = MagicMock(return_value=AsyncStream([
            {"type": "error", "content": "Provider timeout"},
        ]))

        adapter = VoiceRuntimeAdapter(mock_runtime, session_id="test-session")
        result = asyncio.run(_collect(adapter.stream_response("test input")))

        assert "Provider timeout" in result

    def test_adapter_preserves_streaming_order(self):
        mock_runtime = MagicMock()
        mock_runtime.handle_message = MagicMock(return_value=AsyncStream([
            {"type": "provider", "content": "First"},
            {"type": "provider", "content": "Second"},
            {"type": "provider", "content": "Third"},
        ]))

        adapter = VoiceRuntimeAdapter(mock_runtime, session_id="test-session")
        result = asyncio.run(_collect(adapter.stream_response("test input")))

        assert result == ["First", "Second", "Third"]

    def test_adapter_does_not_stringify_dicts(self):
        mock_runtime = MagicMock()
        mock_runtime.handle_message = MagicMock(return_value=AsyncStream([
            {"type": "provider", "content": "Normal text"},
            {"type": "metadata", "content": {"key": "value"}},
        ]))

        adapter = VoiceRuntimeAdapter(mock_runtime, session_id="test-session")
        result = asyncio.run(_collect(adapter.stream_response("test input")))

        assert result == ["Normal text"]
        assert not any("{" in r for r in result)

    def test_adapter_speaks_runtime_exception(self):
        mock_runtime = MagicMock()
        mock_runtime.handle_message = MagicMock(side_effect=RuntimeError("Connection lost"))

        adapter = VoiceRuntimeAdapter(mock_runtime, session_id="test-session")
        result = asyncio.run(_collect(adapter.stream_response("test input")))

        assert len(result) == 1
        assert "Connection lost" in result[0]

    def test_adapter_uses_session_id(self):
        mock_runtime = MagicMock()
        mock_runtime.handle_message = MagicMock(return_value=AsyncStream([
            {"type": "provider", "content": "ok"},
        ]))

        adapter = VoiceRuntimeAdapter(mock_runtime, session_id="my-session")
        asyncio.run(_collect(adapter.stream_response("test input")))

        mock_runtime.handle_message.assert_called_once_with("my-session", "test input")


class TestRuntimeAdapterV2:
    def test_v2_stream_response_filters_provider_only(self):
        mock_runtime = MagicMock()
        mock_runtime.handle_message = MagicMock(return_value=AsyncStream([
            {"type": "provider", "content": "Response"},
            {"type": "tool", "content": "tool result"},
        ]))

        adapter = VoiceRuntimeAdapterV2(mock_runtime)
        result = asyncio.run(_collect(adapter.stream_response("sess-1", "hello")))

        assert result == ["Response"]

    def test_v2_stream_resume_filters_provider_only(self):
        mock_runtime = MagicMock()
        mock_runtime.resume = MagicMock(return_value=AsyncStream([
            {"type": "provider", "content": "Resumed"},
        ]))

        adapter = VoiceRuntimeAdapterV2(mock_runtime)
        result = asyncio.run(_collect(adapter.stream_resume("sess-1", "task-1", {})))

        assert result == ["Resumed"]

    def test_v2_error_on_runtime_exception(self):
        mock_runtime = MagicMock()
        mock_runtime.handle_message = MagicMock(side_effect=Exception("boom"))

        adapter = VoiceRuntimeAdapterV2(mock_runtime)
        result = asyncio.run(_collect(adapter.stream_response("sess-1", "hello")))

        assert len(result) == 1
        assert "boom" in result[0]

    def test_v2_emit_voice_event(self):
        mock_runtime = MagicMock()
        mock_runtime._event_callback = None

        adapter = VoiceRuntimeAdapterV2(mock_runtime)
        from app.voice.events import VoiceEvent
        adapter.emit_voice_event(VoiceEvent.VOICE_SPEAKING, {"text": "hello"})

        assert mock_runtime._event_callback is None


# ---------------------------------------------------------------------------
# Import boundary verification
# ---------------------------------------------------------------------------


def test_adapter_imports_only_runtime():
    """VoiceRuntimeAdapter must only depend on ProductionAgentRuntime."""
    import inspect
    from app.voice import runtime_adapter

    source = inspect.getsource(runtime_adapter)
    assert "from app.core.cap" not in source
    assert "from app.core.gambit" not in source
    assert "from app.workflow" not in source
    assert "from app.providers" not in source
    assert "from app.internet" not in source
    assert "from app.memory" not in source
    assert "from app.tools" not in source
    assert "from app.runtime.dispatcher" not in source


def test_adapter_does_not_import_voice_subsystem_internals():
    """The adapter must not import voice internals directly."""
    import inspect
    from app.voice import runtime_adapter

    source = inspect.getsource(runtime_adapter)
    assert "from app.voice.voice_manager" not in source
    assert "from app.voice.stt" not in source
    assert "from app.voice.tts" not in source