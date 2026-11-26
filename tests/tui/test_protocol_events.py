"""Tests for structured protocol event rendering in Textual TUI (M5).

These tests verify that the TUI correctly renders structured protocol events
(Search, File, Assistant, Error) as defined in the protocol specification.
"""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Label
from app.tui.conversation import ConversationPanel
from app.tui.models import ConversationMessage
from app.tui.renderer import (
    ConversationRenderer,
    RenderedToolMessage,
    RenderedSearchResultsMessage,
    RenderedFileEventMessage,
    RenderedAssistantEventMessage,
    RenderedErrorMessage,
    RenderedSystemMessage,
)


class ProtocolEventsApp(App):
    def compose(self) -> ComposeResult:
        yield ConversationPanel(id="conv")


# =============================================================================
# Search Event Rendering Tests
# =============================================================================

@pytest.mark.asyncio
async def test_render_search_started_event():
    """SEARCH.STARTED event renders as a system message with query and backend."""
    app = ProtocolEventsApp()
    async with app.run_test() as pilot:
        conv = app.query_one("#conv", ConversationPanel)

        payload = {
            "event_type": "SEARCH.STARTED",
            "payload": {
                "query": "rust tutorial",
                "backend": "duckduckgo",
                "filters": {"region": "us"},
                "request_id": "req-123"
            }
        }

        msg = ConversationMessage(
            role="tool",
            content=payload,
            action="search_started",
            show_header=True
        )
        widget = conv._append_message(msg)
        await pilot.pause()

        # Should use RenderedSearchResultsMessage or similar structured type
        assert widget.__class__.__name__ == "RenderedSearchResultsMessage"

        # Check for structured content - should have separate labels for query/backend
        labels = widget.query(Label)
        label_texts = [str(l.content) for l in labels]
        combined = " ".join(label_texts)
        assert "rust tutorial" in combined
        assert "duckduckgo" in combined
        assert "SEARCH.STARTED" in combined or "Search started" in combined


@pytest.mark.asyncio
async def test_render_search_completed_event():
    """SEARCH.COMPLETED event renders results with titles, URLs, snippets, sources."""
    app = ProtocolEventsApp()
    async with app.run_test() as pilot:
        conv = app.query_one("#conv", ConversationPanel)

        payload = {
            "event_type": "SEARCH.COMPLETED",
            "payload": {
                "query": "rust tutorial",
                "backend": "duckduckgo",
                "results": [
                    {
                        "title": "Rust Programming Language",
                        "url": "https://rust-lang.org",
                        "snippet": "Official Rust website",
                        "source": "web"
                    },
                    {
                        "title": "Rust by Example",
                        "url": "https://doc.rust-lang.org/rust-by-example/",
                        "snippet": "Learn Rust by example",
                        "source": "web"
                    }
                ],
                "result_count": 2,
                "request_id": "req-123"
            }
        }

        msg = ConversationMessage(
            role="tool",
            content=payload,
            action="search_completed",
            show_header=True
        )
        widget = conv._append_message(msg)
        await pilot.pause()

        # Should use structured search results message type
        assert widget.__class__.__name__ == "RenderedSearchResultsMessage"

        # Check for structured results - each result should be a separate label or container
        labels = widget.query(Label)
        label_texts = [str(l.content) for l in labels]
        combined = " ".join(label_texts)

        # Verify each result appears
        assert "Rust Programming Language" in combined
        assert "https://rust-lang.org" in combined
        assert "Official Rust website" in combined
        assert "Rust by Example" in combined
        assert "doc.rust-lang.org" in combined


@pytest.mark.asyncio
async def test_render_search_failed_event():
    """SEARCH.FAILED event renders error with error code and message."""
    app = ProtocolEventsApp()
    async with app.run_test() as pilot:
        conv = app.query_one("#conv", ConversationPanel)

        payload = {
            "event_type": "SEARCH.FAILED",
            "payload": {
                "query": "rust tutorial",
                "backend": "duckduckgo",
                "error_code": "BACKEND_UNAVAILABLE",
                "error_message": "Search backend temporarily unavailable",
                "request_id": "req-123"
            }
        }

        msg = ConversationMessage(
            role="tool",
            content=payload,
            action="search_failed",
            show_header=True
        )
        widget = conv._append_message(msg)
        await pilot.pause()

        assert widget.__class__.__name__ == "RenderedSearchResultsMessage"

        labels = widget.query(Label)
        label_texts = [str(l.content) for l in labels]
        combined = " ".join(label_texts)
        assert "BACKEND_UNAVAILABLE" in combined
        assert "Search backend temporarily unavailable" in combined


# =============================================================================
# File Event Rendering Tests
# =============================================================================

@pytest.mark.asyncio
async def test_render_file_read_started_event():
    """FILE.READ_STARTED event renders with safe path and status."""
    app = ProtocolEventsApp()
    async with app.run_test() as pilot:
        conv = app.query_one("#conv", ConversationPanel)

        payload = {
            "event_type": "FILE.READ_STARTED",
            "payload": {
                "path": "/home/user/project/src/main.rs",
                "offset": 0,
                "limit": 1024,
                "request_id": "req-456"
            }
        }

        msg = ConversationMessage(
            role="tool",
            content=payload,
            action="file_read_started",
            show_header=True
        )
        widget = conv._append_message(msg)
        await pilot.pause()

        # Should use RenderedFileEventMessage
        assert widget.__class__.__name__ == "RenderedFileEventMessage"

        labels = widget.query(Label)
        label_texts = [str(l.content) for l in labels]
        combined = " ".join(label_texts)
        assert "main.rs" in combined
        assert "Reading" in combined or "read" in combined.lower()
        assert "FILE.READ_STARTED" in combined or "Read started" in combined


@pytest.mark.asyncio
async def test_render_file_read_completed_event():
    """FILE.READ_COMPLETED event renders file content preview with size/encoding."""
    app = ProtocolEventsApp()
    async with app.run_test() as pilot:
        conv = app.query_one("#conv", ConversationPanel)

        payload = {
            "event_type": "FILE.READ_COMPLETED",
            "payload": {
                "path": "/home/user/project/src/main.rs",
                "content": "fn main() {\n    println!(\"Hello, world!\");\n}",
                "size": 48,
                "encoding": "utf-8",
                "request_id": "req-456"
            }
        }

        msg = ConversationMessage(
            role="tool",
            content=payload,
            action="file_read_completed",
            show_header=True
        )
        widget = conv._append_message(msg)
        await pilot.pause()

        assert widget.__class__.__name__ == "RenderedFileEventMessage"

        labels = widget.query(Label)
        label_texts = [str(l.content) for l in labels]
        combined = " ".join(label_texts)
        assert "main.rs" in combined
        assert "fn main" in combined
        assert "48" in combined
        assert "utf-8" in combined


@pytest.mark.asyncio
async def test_render_file_write_started_event():
    """FILE.WRITE_STARTED event renders with path, content length, and mode."""
    app = ProtocolEventsApp()
    async with app.run_test() as pilot:
        conv = app.query_one("#conv", ConversationPanel)

        payload = {
            "event_type": "FILE.WRITE_STARTED",
            "payload": {
                "path": "/home/user/project/src/lib.rs",
                "content_length": 256,
                "mode": "write",
                "request_id": "req-789"
            }
        }

        msg = ConversationMessage(
            role="tool",
            content=payload,
            action="file_write_started",
            show_header=True
        )
        widget = conv._append_message(msg)
        await pilot.pause()

        assert widget.__class__.__name__ == "RenderedFileEventMessage"

        labels = widget.query(Label)
        label_texts = [str(l.content) for l in labels]
        combined = " ".join(label_texts)
        assert "lib.rs" in combined
        assert "256" in combined
        assert "write" in combined.lower()


@pytest.mark.asyncio
async def test_render_file_write_completed_event():
    """FILE.WRITE_COMPLETED event renders with path and bytes written."""
    app = ProtocolEventsApp()
    async with app.run_test() as pilot:
        conv = app.query_one("#conv", ConversationPanel)

        payload = {
            "event_type": "FILE.WRITE_COMPLETED",
            "payload": {
                "path": "/home/user/project/src/lib.rs",
                "bytes_written": 256,
                "request_id": "req-789"
            }
        }

        msg = ConversationMessage(
            role="tool",
            content=payload,
            action="file_write_completed",
            show_header=True
        )
        widget = conv._append_message(msg)
        await pilot.pause()

        assert widget.__class__.__name__ == "RenderedFileEventMessage"

        labels = widget.query(Label)
        label_texts = [str(l.content) for l in labels]
        combined = " ".join(label_texts)
        assert "lib.rs" in combined
        assert "256" in combined
        assert "written" in combined.lower() or "complete" in combined.lower()


@pytest.mark.asyncio
async def test_render_file_list_started_event():
    """FILE.LIST_STARTED event renders with directory path and recursive flag."""
    app = ProtocolEventsApp()
    async with app.run_test() as pilot:
        conv = app.query_one("#conv", ConversationPanel)

        payload = {
            "event_type": "FILE.LIST_STARTED",
            "payload": {
                "path": "/home/user/project/src",
                "recursive": True,
                "request_id": "req-999"
            }
        }

        msg = ConversationMessage(
            role="tool",
            content=payload,
            action="file_list_started",
            show_header=True
        )
        widget = conv._append_message(msg)
        await pilot.pause()

        assert widget.__class__.__name__ == "RenderedFileEventMessage"

        labels = widget.query(Label)
        label_texts = [str(l.content) for l in labels]
        combined = " ".join(label_texts)
        assert "src" in combined
        assert "recursive" in combined.lower() or "true" in combined.lower()


@pytest.mark.asyncio
async def test_render_file_list_completed_event():
    """FILE.LIST_COMPLETED event renders directory entries with count."""
    app = ProtocolEventsApp()
    async with app.run_test() as pilot:
        conv = app.query_one("#conv", ConversationPanel)

        payload = {
            "event_type": "FILE.LIST_COMPLETED",
            "payload": {
                "path": "/home/user/project/src",
                "entries": [
                    {"name": "main.rs", "type": "file", "size": 48},
                    {"name": "lib.rs", "type": "file", "size": 256},
                    {"name": "tests", "type": "folder", "size": 0}
                ],
                "entry_count": 3,
                "request_id": "req-999"
            }
        }

        msg = ConversationMessage(
            role="tool",
            content=payload,
            action="file_list_completed",
            show_header=True
        )
        widget = conv._append_message(msg)
        await pilot.pause()

        assert widget.__class__.__name__ == "RenderedFileEventMessage"

        labels = widget.query(Label)
        label_texts = [str(l.content) for l in labels]
        combined = " ".join(label_texts)
        assert "main.rs" in combined
        assert "lib.rs" in combined
        assert "tests" in combined
        assert "3" in combined


# =============================================================================
# Assistant Event Rendering Tests
# =============================================================================

@pytest.mark.asyncio
async def test_render_assistant_message_started_event():
    """ASSISTANT.MESSAGE_STARTED event renders model/provider info."""
    app = ProtocolEventsApp()
    async with app.run_test() as pilot:
        conv = app.query_one("#conv", ConversationPanel)

        payload = {
            "event_type": "ASSISTANT.MESSAGE_STARTED",
            "payload": {
                "model_id": "gpt-4o",
                "provider_id": "openai",
                "request_id": "req-111",
                "trace_id": "trace-abc"
            }
        }

        msg = ConversationMessage(
            role="tool",
            content=payload,
            action="assistant_started",
            show_header=True
        )
        widget = conv._append_message(msg)
        await pilot.pause()

        assert widget.__class__.__name__ == "RenderedAssistantEventMessage"

        labels = widget.query(Label)
        label_texts = [str(l.content) for l in labels]
        combined = " ".join(label_texts)
        assert "gpt-4o" in combined
        assert "openai" in combined


@pytest.mark.asyncio
async def test_render_assistant_token_event():
    """ASSISTANT.TOKEN event streams tokens to assistant message."""
    app = ProtocolEventsApp()
    async with app.run_test() as pilot:
        conv = app.query_one("#conv", ConversationPanel)

        # This tests the streaming token path via append_stream_token
        conv.append_assistant_start()
        conv.append_stream_token("Hello")
        conv.append_stream_token(" world")
        conv.append_assistant_end()
        await pilot.pause()

        # Should have an assistant message with accumulated content
        from app.tui.renderer import RenderedAssistantMessage
        assistant_msgs = conv.query(RenderedAssistantMessage)
        assert len(assistant_msgs) == 1

        content = assistant_msgs[0].message.content
        assert "Hello world" in content


@pytest.mark.asyncio
async def test_render_assistant_message_completed_event():
    """ASSISTANT.MESSAGE_COMPLETED event finalizes with content, finish_reason, usage."""
    app = ProtocolEventsApp()
    async with app.run_test() as pilot:
        conv = app.query_one("#conv", ConversationPanel)

        payload = {
            "event_type": "ASSISTANT.MESSAGE_COMPLETED",
            "payload": {
                "model_id": "gpt-4o",
                "provider_id": "openai",
                "content": "Hello! I can help you with Rust.",
                "finish_reason": "stop",
                "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
                "request_id": "req-111",
                "trace_id": "trace-abc"
            }
        }

        msg = ConversationMessage(
            role="tool",
            content=payload,
            action="assistant_completed",
            show_header=True
        )
        widget = conv._append_message(msg)
        await pilot.pause()

        assert widget.__class__.__name__ == "RenderedAssistantEventMessage"

        labels = widget.query(Label)
        label_texts = [str(l.content) for l in labels]
        combined = " ".join(label_texts)
        assert "gpt-4o" in combined
        assert "Hello! I can help you with Rust." in combined
        assert "stop" in combined
        assert "18" in combined


@pytest.mark.asyncio
async def test_render_assistant_error_event():
    """ASSISTANT.ERROR event renders error code and message."""
    app = ProtocolEventsApp()
    async with app.run_test() as pilot:
        conv = app.query_one("#conv", ConversationPanel)

        payload = {
            "event_type": "ASSISTANT.ERROR",
            "payload": {
                "model_id": "gpt-4o",
                "provider_id": "openai",
                "error_code": "RATE_LIMITED",
                "error_message": "Rate limit exceeded. Try again later.",
                "request_id": "req-111",
                "trace_id": "trace-abc"
            }
        }

        msg = ConversationMessage(
            role="tool",
            content=payload,
            action="assistant_error",
            show_header=True
        )
        widget = conv._append_message(msg)
        await pilot.pause()

        assert widget.__class__.__name__ == "RenderedAssistantEventMessage"

        labels = widget.query(Label)
        label_texts = [str(l.content) for l in labels]
        combined = " ".join(label_texts)
        assert "RATE_LIMITED" in combined
        assert "Rate limit exceeded" in combined


# =============================================================================
# Error Event Rendering Tests
# =============================================================================

@pytest.mark.asyncio
async def test_render_generic_error_event():
    """Generic error event renders error message."""
    app = ProtocolEventsApp()
    async with app.run_test() as pilot:
        conv = app.query_one("#conv", ConversationPanel)

        payload = {
            "event_type": "ERROR",
            "payload": {
                "error_code": "EXECUTION_FAILED",
                "error_message": "Pipeline execution failed",
                "details": {"stage": "planning"}
            }
        }

        msg = ConversationMessage(
            role="error",
            content=payload,
            error=True
        )
        widget = conv._append_message(msg)
        await pilot.pause()

        # Should use RenderedErrorMessage
        assert widget.__class__.__name__ == "RenderedErrorMessage"

        labels = widget.query(Label)
        label_texts = [str(l.content) for l in labels]
        combined = " ".join(label_texts)
        assert "EXECUTION_FAILED" in combined
        assert "Pipeline execution failed" in combined


# =============================================================================
# Legacy Tool Output Fallback Tests
# =============================================================================

@pytest.mark.asyncio
async def test_render_legacy_tool_output_fallback():
    """Unknown/legacy tool output falls back to formatted text (not JSON)."""
    app = ProtocolEventsApp()
    async with app.run_test() as pilot:
        conv = app.query_one("#conv", ConversationPanel)

        # Legacy format: simple dict without event_type
        payload = {
            "tool": "custom_tool",
            "output": "Some output",
            "status": "ok"
        }

        msg = ConversationMessage(
            role="tool",
            content=payload,
            action="custom_tool",
            show_header=True
        )
        widget = conv._append_message(msg)
        await pilot.pause()

        # Should fall back to RenderedToolMessage
        assert widget.__class__.__name__ == "RenderedToolMessage"

        labels = widget.query(Label)
        label_texts = [str(l.content) for l in labels]
        combined = " ".join(label_texts)
        assert "custom_tool" in combined
        assert "Some output" in combined
        # Should NOT be raw JSON
        assert '{"tool": "custom_tool"' not in combined


# =============================================================================
# Malformed Payload Handling Tests
# =============================================================================

@pytest.mark.asyncio
async def test_render_malformed_payload_missing_event_type():
    """Missing event_type falls back gracefully."""
    app = ProtocolEventsApp()
    async with app.run_test() as pilot:
        conv = app.query_one("#conv", ConversationPanel)

        payload = {
            "payload": {
                "query": "test",
                "backend": "duckduckgo"
            }
        }

        msg = ConversationMessage(
            role="tool",
            content=payload,
            action="search",
            show_header=True
        )
        widget = conv._append_message(msg)
        await pilot.pause()

        # Should not crash, should fall back to RenderedToolMessage
        assert widget.__class__.__name__ in ("RenderedToolMessage", "RenderedSearchResultsMessage")

        labels = widget.query(Label)
        label_texts = [str(l.content) for l in labels]
        combined = " ".join(label_texts)
        assert len(combined) > 0


@pytest.mark.asyncio
async def test_render_malformed_payload_missing_payload():
    """Missing payload field falls back gracefully."""
    app = ProtocolEventsApp()
    async with app.run_test() as pilot:
        conv = app.query_one("#conv", ConversationPanel)

        payload = {
            "event_type": "SEARCH.COMPLETED"
            # missing payload
        }

        msg = ConversationMessage(
            role="tool",
            content=payload,
            action="search_completed",
            show_header=True
        )
        widget = conv._append_message(msg)
        await pilot.pause()

        # Should not crash
        assert widget.__class__.__name__ in ("RenderedToolMessage", "RenderedSearchResultsMessage")

        labels = widget.query(Label)
        label_texts = [str(l.content) for l in labels]
        combined = " ".join(label_texts)
        assert len(combined) > 0


@pytest.mark.asyncio
async def test_render_malformed_payload_invalid_results():
    """Invalid results structure (non-list) falls back gracefully."""
    app = ProtocolEventsApp()
    async with app.run_test() as pilot:
        conv = app.query_one("#conv", ConversationPanel)

        payload = {
            "event_type": "SEARCH.COMPLETED",
            "payload": {
                "query": "test",
                "backend": "duckduckgo",
                "results": "not a list",  # invalid
                "result_count": 0,
                "request_id": "req-123"
            }
        }

        msg = ConversationMessage(
            role="tool",
            content=payload,
            action="search_completed",
            show_header=True
        )
        widget = conv._append_message(msg)
        await pilot.pause()

        # Should not crash
        assert widget.__class__.__name__ in ("RenderedToolMessage", "RenderedSearchResultsMessage")

        labels = widget.query(Label)
        label_texts = [str(l.content) for l in labels]
        combined = " ".join(label_texts)
        assert len(combined) > 0


# =============================================================================
# Approval/Cancellation Compatibility Tests (Step 2)
# =============================================================================

@pytest.mark.asyncio
async def test_approval_allow_button_sends_backend_approval_id():
    """Allow button sends backend approval_id + decision, not local decision."""
    # This test will verify that clicking Allow sends the approval_id from the
    # backend pause event, not a locally generated decision
    pass  # Implementation in Step 2


@pytest.mark.asyncio
async def test_approval_deny_button_sends_backend_approval_id():
    """Deny button sends backend approval_id + decision."""
    pass  # Implementation in Step 2


@pytest.mark.asyncio
async def test_cancellation_renders_notice():
    """Cancellation event renders as a system notice."""
    app = ProtocolEventsApp()
    async with app.run_test() as pilot:
        conv = app.query_one("#conv", ConversationPanel)

        payload = {
            "event_type": "CANCELLATION",
            "payload": {
                "reason": "User cancelled",
                "execution_id": "exec-123"
            }
        }

        msg = ConversationMessage(
            role="system",
            content=payload
        )
        widget = conv._append_message(msg)
        await pilot.pause()

        # Should use RenderedSystemMessage
        assert widget.__class__.__name__ == "RenderedSystemMessage"

        labels = widget.query(Label)
        label_texts = [str(l.content) for l in labels]
        combined = " ".join(label_texts)
        assert "cancelled" in combined.lower() or "Cancellation" in combined


@pytest.mark.asyncio
async def test_reconnect_renders_resync_notice():
    """Reconnection (RESYNC) renders as a notice with sequence info."""
    app = ProtocolEventsApp()
    async with app.run_test() as pilot:
        conv = app.query_one("#conv", ConversationPanel)

        payload = {
            "event_type": "RESYNC",
            "payload": {
                "expected_sequence": 10,
                "actual_sequence": 15,
                "message": "Resynchronized after gap"
            }
        }

        msg = ConversationMessage(
            role="system",
            content=payload
        )
        widget = conv._append_message(msg)
        await pilot.pause()

        # Should use RenderedSystemMessage
        assert widget.__class__.__name__ == "RenderedSystemMessage"

        labels = widget.query(Label)
        label_texts = [str(l.content) for l in labels]
        combined = " ".join(label_texts)
        assert "Resync" in combined or "resync" in combined.lower()
        assert "10" in combined
        assert "15" in combined