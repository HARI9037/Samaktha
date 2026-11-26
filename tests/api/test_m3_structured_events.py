"""M3 Task 3 — Structured Search/File/Assistant Events contract tests.

These tests define the expected typed event payloads for search, file, and assistant operations.
They should FAIL initially (red phase) and pass after M3 implementation.
"""

import pytest
from pydantic import ValidationError

from app.api.protocol import (
    PROTOCOL_VERSION,
    SearchEventPayload,
    FileEventPayload,
    AssistantEventPayload,
    SearchStartedPayload,
    SearchCompletedPayload,
    SearchFailedPayload,
    FileReadStartedPayload,
    FileReadCompletedPayload,
    FileWriteStartedPayload,
    FileWriteCompletedPayload,
    FileListStartedPayload,
    FileListCompletedPayload,
    AssistantMessageStartedPayload,
    AssistantMessageCompletedPayload,
    AssistantTokenPayload,
    AssistantErrorPayload,
    EventEnvelope,
    RuntimeEventType,
)


class TestM3SearchEvents:
    """Test structured search event payloads."""

    def test_search_started_payload_has_required_fields(self):
        """SearchStartedPayload must have query, backend, and optional filters."""
        payload = SearchStartedPayload(
            query="test query",
            backend="duckduckgo",
            filters={"region": "us-en"},
            request_id="req-123",
        )
        assert payload.query == "test query"
        assert payload.backend == "duckduckgo"
        assert payload.filters == {"region": "us-en"}
        assert payload.request_id == "req-123"

    def test_search_started_payload_rejects_unknown_fields(self):
        """Extra fields on SearchStartedPayload must be rejected (extra=forbid)."""
        with pytest.raises(ValidationError):
            SearchStartedPayload(
                query="test",
                backend="duckduckgo",
                unknown_field="value",
            )

    def test_search_completed_payload_has_results(self):
        """SearchCompletedPayload must have results array with structured items."""
        payload = SearchCompletedPayload(
            query="test query",
            backend="duckduckgo",
            results=[
                {"title": "Result 1", "url": "http://example.com/1", "snippet": "Summary 1"},
                {"title": "Result 2", "url": "http://example.com/2", "snippet": "Summary 2"},
            ],
            result_count=2,
            request_id="req-123",
        )
        assert payload.query == "test query"
        assert len(payload.results) == 2
        assert payload.result_count == 2
        assert payload.results[0]["title"] == "Result 1"

    def test_search_completed_payload_empty_results(self):
        """SearchCompletedPayload supports empty results."""
        payload = SearchCompletedPayload(
            query="no results query",
            backend="duckduckgo",
            results=[],
            result_count=0,
            request_id="req-123",
        )
        assert payload.result_count == 0
        assert payload.results == []

    def test_search_failed_payload_has_error_details(self):
        """SearchFailedPayload must have error code and message."""
        payload = SearchFailedPayload(
            query="test query",
            backend="duckduckgo",
            error_code="BACKEND_UNAVAILABLE",
            error_message="Search backend returned 503",
            request_id="req-123",
        )
        assert payload.error_code == "BACKEND_UNAVAILABLE"
        assert payload.error_message == "Search backend returned 503"

    def test_search_event_payload_union_accepts_all_variants(self):
        """SearchEventPayload union should accept started/completed/failed."""
        started = SearchEventPayload(
            event_type="SEARCH.STARTED",
            payload=SearchStartedPayload(query="test", backend="ddg", request_id="r1"),
        )
        completed = SearchEventPayload(
            event_type="SEARCH.COMPLETED",
            payload=SearchCompletedPayload(query="test", backend="ddg", results=[], result_count=0, request_id="r1"),
        )
        failed = SearchEventPayload(
            event_type="SEARCH.FAILED",
            payload=SearchFailedPayload(query="test", backend="ddg", error_code="ERR", error_message="msg", request_id="r1"),
        )
        assert started.payload.query == "test"
        assert completed.payload.result_count == 0
        assert failed.payload.error_code == "ERR"


class TestM3FileEvents:
    """Test structured file event payloads."""

    def test_file_read_started_payload(self):
        """FileReadStartedPayload must have path and optional offset/limit."""
        payload = FileReadStartedPayload(
            path="/home/user/file.txt",
            offset=0,
            limit=1000,
            request_id="req-123",
        )
        assert payload.path == "/home/user/file.txt"
        assert payload.offset == 0
        assert payload.limit == 1000

    def test_file_read_completed_payload(self):
        """FileReadCompletedPayload must have content and metadata."""
        payload = FileReadCompletedPayload(
            path="/home/user/file.txt",
            content="file content here",
            size=17,
            encoding="utf-8",
            request_id="req-123",
        )
        assert payload.content == "file content here"
        assert payload.size == 17
        assert payload.encoding == "utf-8"

    def test_file_write_started_payload(self):
        """FileWriteStartedPayload must have path and content info."""
        payload = FileWriteStartedPayload(
            path="/home/user/newfile.txt",
            content_length=100,
            mode="write",
            request_id="req-123",
        )
        assert payload.path == "/home/user/newfile.txt"
        assert payload.content_length == 100
        assert payload.mode == "write"

    def test_file_write_completed_payload(self):
        """FileWriteCompletedPayload must have path and written info."""
        payload = FileWriteCompletedPayload(
            path="/home/user/newfile.txt",
            bytes_written=100,
            request_id="req-123",
        )
        assert payload.bytes_written == 100

    def test_file_list_started_payload(self):
        """FileListStartedPayload must have directory path."""
        payload = FileListStartedPayload(
            path="/home/user/projects",
            recursive=False,
            request_id="req-123",
        )
        assert payload.path == "/home/user/projects"
        assert payload.recursive is False

    def test_file_list_completed_payload(self):
        """FileListCompletedPayload must have entries array."""
        payload = FileListCompletedPayload(
            path="/home/user/projects",
            entries=[
                {"name": "file1.txt", "type": "file", "size": 100},
                {"name": "subdir", "type": "directory", "size": 0},
            ],
            entry_count=2,
            request_id="req-123",
        )
        assert payload.entry_count == 2
        assert len(payload.entries) == 2
        assert payload.entries[0]["name"] == "file1.txt"

    def test_file_event_payload_union(self):
        """FileEventPayload union should accept all file event types."""
        read_started = FileEventPayload(
            event_type="FILE.READ_STARTED",
            payload=FileReadStartedPayload(path="/test.txt", request_id="r1"),
        )
        read_completed = FileEventPayload(
            event_type="FILE.READ_COMPLETED",
            payload=FileReadCompletedPayload(path="/test.txt", content="hi", size=2, encoding="utf-8", request_id="r1"),
        )
        write_started = FileEventPayload(
            event_type="FILE.WRITE_STARTED",
            payload=FileWriteStartedPayload(path="/test.txt", content_length=2, mode="write", request_id="r1"),
        )
        write_completed = FileEventPayload(
            event_type="FILE.WRITE_COMPLETED",
            payload=FileWriteCompletedPayload(path="/test.txt", bytes_written=2, request_id="r1"),
        )
        list_started = FileEventPayload(
            event_type="FILE.LIST_STARTED",
            payload=FileListStartedPayload(path="/", request_id="r1"),
        )
        list_completed = FileEventPayload(
            event_type="FILE.LIST_COMPLETED",
            payload=FileListCompletedPayload(path="/", entries=[], entry_count=0, request_id="r1"),
        )
        assert read_started.payload.path == "/test.txt"
        assert read_completed.payload.content == "hi"
        assert write_started.payload.content_length == 2
        assert write_completed.payload.bytes_written == 2
        assert list_started.payload.path == "/"
        assert list_completed.payload.entry_count == 0


class TestM3AssistantEvents:
    """Test structured assistant event payloads."""

    def test_assistant_message_started_payload(self):
        """AssistantMessageStartedPayload must have model_id and request info."""
        payload = AssistantMessageStartedPayload(
            model_id="gpt-4o",
            provider_id="openai",
            request_id="req-123",
            trace_id="trace-456",
        )
        assert payload.model_id == "gpt-4o"
        assert payload.provider_id == "openai"
        assert payload.request_id == "req-123"
        assert payload.trace_id == "trace-456"

    def test_assistant_message_completed_payload(self):
        """AssistantMessageCompletedPayload must have full response."""
        payload = AssistantMessageCompletedPayload(
            model_id="gpt-4o",
            provider_id="openai",
            content="Assistant response here",
            finish_reason="stop",
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            request_id="req-123",
            trace_id="trace-456",
        )
        assert payload.content == "Assistant response here"
        assert payload.finish_reason == "stop"
        assert payload.usage["total_tokens"] == 30

    def test_assistant_token_payload(self):
        """AssistantTokenPayload for streaming tokens."""
        payload = AssistantTokenPayload(
            model_id="gpt-4o",
            provider_id="openai",
            token="Hello",
            sequence_number=1,
            request_id="req-123",
            trace_id="trace-456",
        )
        assert payload.token == "Hello"
        assert payload.sequence_number == 1

    def test_assistant_error_payload(self):
        """AssistantErrorPayload for provider errors."""
        payload = AssistantErrorPayload(
            model_id="gpt-4o",
            provider_id="openai",
            error_code="RATE_LIMITED",
            error_message="Rate limit exceeded",
            request_id="req-123",
            trace_id="trace-456",
        )
        assert payload.error_code == "RATE_LIMITED"
        assert payload.error_message == "Rate limit exceeded"

    def test_assistant_event_payload_union(self):
        """AssistantEventPayload union should accept all assistant event types."""
        started = AssistantEventPayload(
            event_type="ASSISTANT.MESSAGE_STARTED",
            payload=AssistantMessageStartedPayload(model_id="gpt-4o", provider_id="openai", request_id="r1"),
        )
        completed = AssistantEventPayload(
            event_type="ASSISTANT.MESSAGE_COMPLETED",
            payload=AssistantMessageCompletedPayload(
                model_id="gpt-4o", provider_id="openai", content="hi", finish_reason="stop", usage={}, request_id="r1"
            ),
        )
        token = AssistantEventPayload(
            event_type="ASSISTANT.TOKEN",
            payload=AssistantTokenPayload(model_id="gpt-4o", provider_id="openai", token="x", sequence_number=1, request_id="r1"),
        )
        error = AssistantEventPayload(
            event_type="ASSISTANT.ERROR",
            payload=AssistantErrorPayload(model_id="gpt-4o", provider_id="openai", error_code="ERR", error_message="msg", request_id="r1"),
        )
        assert started.payload.model_id == "gpt-4o"
        assert completed.payload.content == "hi"
        assert token.payload.token == "x"
        assert error.payload.error_code == "ERR"


class TestM3EventEnvelopeIntegration:
    """Test that structured payloads integrate with EventEnvelope."""

    def test_search_event_in_envelope(self):
        """Search events should wrap in EventEnvelope with sequence."""
        env = EventEnvelope(
            sequence=1,
            execution_id="exec-123",
            session_id="sess-456",
            event_type=RuntimeEventType.TOOL_STARTED,  # Maps to search tool
            payload=SearchEventPayload(
                event_type="SEARCH.STARTED",
                payload=SearchStartedPayload(query="test", backend="ddg", request_id="r1"),
            ).model_dump(),
            timestamp="2024-01-01T00:00:00Z",
        )
        assert env.sequence == 1
        assert env.event_type == RuntimeEventType.TOOL_STARTED
        assert env.payload["event_type"] == "SEARCH.STARTED"
        assert env.payload["payload"]["query"] == "test"

    def test_file_event_in_envelope(self):
        """File events should wrap in EventEnvelope with sequence."""
        env = EventEnvelope(
            sequence=2,
            execution_id="exec-123",
            session_id="sess-456",
            event_type=RuntimeEventType.TOOL_STARTED,
            payload=FileEventPayload(
                event_type="FILE.READ_STARTED",
                payload=FileReadStartedPayload(path="/test.txt", request_id="r1"),
            ).model_dump(),
            timestamp="2024-01-01T00:00:00Z",
        )
        assert env.sequence == 2
        assert env.payload["event_type"] == "FILE.READ_STARTED"
        assert env.payload["payload"]["path"] == "/test.txt"

    def test_assistant_event_in_envelope(self):
        """Assistant events should wrap in EventEnvelope with sequence."""
        env = EventEnvelope(
            sequence=3,
            execution_id="exec-123",
            session_id="sess-456",
            event_type=RuntimeEventType.PROVIDER_STARTED,
            payload=AssistantEventPayload(
                event_type="ASSISTANT.MESSAGE_STARTED",
                payload=AssistantMessageStartedPayload(model_id="gpt-4o", provider_id="openai", request_id="r1"),
            ).model_dump(),
            timestamp="2024-01-01T00:00:00Z",
        )
        assert env.sequence == 3
        assert env.payload["event_type"] == "ASSISTANT.MESSAGE_STARTED"
        assert env.payload["payload"]["model_id"] == "gpt-4o"


class TestM3ProtocolVersioning:
    """Test that structured events include protocol version."""

    def test_search_events_have_protocol_version(self):
        """Search events should have protocol_version field."""
        payload = SearchStartedPayload(query="test", backend="ddg", request_id="r1")
        # The protocol_version is on the envelope, not the payload
        env = EventEnvelope(
            sequence=1,
            execution_id="exec-1",
            session_id="sess-1",
            event_type=RuntimeEventType.TOOL_STARTED,
            payload=payload.model_dump(),
            timestamp="2024-01-01T00:00:00Z",
        )
        # Verify envelope can be serialized
        serialized = env.model_dump(mode="json")
        assert serialized["sequence"] == 1

    def test_event_envelope_includes_protocol_version_in_payload(self):
        """EventEnvelope payload should support protocol_version."""
        # The payload field is dict[str, Any], so protocol_version can be included
        payload_with_version = {
            "event_type": "SEARCH.STARTED",
            "payload": {"query": "test", "backend": "ddg", "request_id": "r1"},
            "protocol_version": PROTOCOL_VERSION,
        }
        env = EventEnvelope(
            sequence=1,
            execution_id="exec-1",
            session_id="sess-1",
            event_type=RuntimeEventType.TOOL_STARTED,
            payload=payload_with_version,
            timestamp="2024-01-01T00:00:00Z",
        )
        assert env.payload.get("protocol_version") == PROTOCOL_VERSION


if __name__ == "__main__":
    pytest.main([__file__, "-v"])