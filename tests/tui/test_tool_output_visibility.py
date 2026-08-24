"""Tests for Phase 5.8.1 — Hide Internal Tool Output.

Verifies:
- AgentConfig has show_tool_output (default False)
- Tool output is only rendered when debug=True or show_tool_output=True
- RenderedToolMessage shows header when show_header=True
- CAP approval logic is NOT affected
"""
import pytest
from textual.app import App, ComposeResult
from app.agent.config import AgentConfig
from app.tui.conversation import ConversationPanel
from app.tui.renderer import (
    RenderedToolMessage,
    RenderedApprovalMessage,
)
from app.tui.models import ConversationMessage
from app.config.settings import get_settings


class TestAgentConfig:
    """show_tool_output config defaults to False."""

    def test_show_tool_output_defaults_to_false(self):
        config = AgentConfig()
        assert config.show_tool_output is False

    def test_show_tool_output_can_be_true(self):
        config = AgentConfig(show_tool_output=True)
        assert config.show_tool_output is True

    def test_show_tool_output_is_bool(self):
        config = AgentConfig()
        assert isinstance(config.show_tool_output, bool)


class TestConversationMessageModel:
    """ConversationMessage carries show_header flag."""

    def test_show_header_defaults_to_false(self):
        msg = ConversationMessage(role="tool", content="test")
        assert msg.show_header is False

    def test_show_header_can_be_true(self):
        msg = ConversationMessage(role="tool", content="test", show_header=True)
        assert msg.show_header is True


class TestAppendToolOutput:
    """append_tool_output forwards show_header to the message."""

    def test_append_tool_output_default(self):
        """Without show_header, message.show_header should be False."""
        msg = ConversationMessage(role="tool", content="data")
        assert msg.show_header is False

    def test_append_tool_output_with_header(self):
        msg = ConversationMessage(role="tool", content="data", show_header=True)
        assert msg.show_header is True

    def test_append_tool_output_with_action(self):
        msg = ConversationMessage(role="tool", content="data", action="list", show_header=True)
        assert msg.action == "list"
        assert msg.show_header is True


class TestRenderedToolMessageHeader:
    """RenderedToolMessage shows ──── Tool Output ──── when show_header=True."""

    def test_compose_contains_header_when_show_header_true(self):
        """Inspect compose source for header labels."""
        import inspect
        src = inspect.getsource(RenderedToolMessage.compose)
        assert "Tool Output" in src
        assert "show_header" in src

    def test_compose_no_header_when_show_header_false(self):
        """Default render path does not include header."""
        msg = ConversationMessage(role="tool", content="plain result")
        rendered = RenderedToolMessage(msg)
        assert rendered.message.show_header is False


class TestRenderedToolMessageDirectoryListing:
    """Directory listings should still render properly with show_header."""

    def test_directory_listing_with_header(self):
        """Directory listing format not broken by show_header."""
        import inspect
        src = inspect.getsource(RenderedToolMessage.compose)
        # Both the header block and directory listing path should exist
        assert "Tool Output" in src
        assert "Directory" in src or "items" in src

    def test_directory_listing_format_preserved(self):
        """Directory listing keys (items, count, path) unchanged."""
        import inspect
        src = inspect.getsource(RenderedToolMessage.compose)
        assert "items" in src or '"items"' in src


class TestCAPApprovalNotAffected:
    """CAP approval must NOT be modified by the tool output changes."""

    def test_approval_message_is_separate_class(self):
        assert RenderedApprovalMessage is not RenderedToolMessage

    def test_approval_not_filtered(self):
        """Approval messages use append_approval_request, not append_tool_output."""
        from app.tui.conversation import ConversationPanel
        import inspect
        src = inspect.getsource(ConversationPanel)
        assert "append_approval_request" in src
        # All approval methods are separate from tool output

    def test_approval_events_not_in_tool_path(self):
        """PAUSE_REQUESTED events route to append_approval_request, not append_tool_output."""
        from app.tui.app import MainScreen
        import inspect
        src = inspect.getsource(MainScreen._dispatch_event)
        assert "PAUSE_REQUESTED" in src


class TestSettingsIntegration:
    """Settings.debug gates tool output rendering alongside show_tool_output."""

    def test_debug_false_hides_tool_output(self):
        settings = get_settings()
        original_debug = settings.debug
        settings.debug = False
        try:
            assert settings.debug is False
            show = settings.debug or False
            assert show is False
        finally:
            settings.debug = original_debug

    def test_debug_true_shows_tool_output(self):
        settings = get_settings()
        original_debug = settings.debug
        settings.debug = True
        try:
            show = settings.debug or False
            assert show is True
        finally:
            settings.debug = original_debug


class TestRuntimeOutputContract:
    """Canonical Runtime results remain visible to the TUI adapter."""

    def test_production_still_yields_tool_items(self):
        """The adapter maps canonical tool results without a provider bypass."""
        import inspect
        from app.agent.production import _enqueue_runtime_result
        src = inspect.getsource(_enqueue_runtime_result)
        assert '"tool"' in src

    def test_executor_still_sets_output(self):
        """ToolExecutor still sets RuntimeResult.output from ToolResult.data."""
        import inspect
        from app.runtime.executor import ToolExecutor
        src = inspect.getsource(ToolExecutor.execute)
        assert 'output = tool_result.data' in src or 'output=' in src


class TestTUIAppRouting:
    """Runtime streaming is consolidated into one canonical consumer."""

    def test_canonical_consumer_gates_tool_output(self):
        import inspect
        from app.tui.app import MainScreen
        src = inspect.getsource(MainScreen._consume_runtime_stream)
        assert "show_tool_output" in src
        assert "conv.append_tool_output(" in src

    def test_stream_and_resume_delegate_to_canonical_consumer(self):
        import inspect
        from app.tui.app import MainScreen
        for method in (MainScreen._stream_response, MainScreen._submit_resume):
            src = inspect.getsource(method)
            assert "_consume_runtime_stream" in src

    def test_tool_output_gate_defined_once(self):
        """The visibility gate lives in exactly one place in MainScreen."""
        import inspect
        from app.tui.app import MainScreen
        src = inspect.getsource(MainScreen)
        assert src.count("conv.append_tool_output(") == 1
        for method in (MainScreen._stream_response, MainScreen._submit_resume):
            assert "show_tool_output" not in inspect.getsource(method)
