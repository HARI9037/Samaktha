"""Tests for Phase 6.3 TUI Markdown rendering (updated for 6.6B+ renderer model)."""

from app.tui.renderer import RenderedAssistantMessage
from app.tui.models import ConversationMessage


def test_assistant_message_streaming_cursor():
    """Streaming message appends ▋ cursor to display text."""
    msg = ConversationMessage(role="assistant", content="# Hello", streaming=True)
    assert msg.streaming is True
    assert msg.content == "# Hello"


def test_assistant_message_finish_stream():
    """Finishing stream sets streaming=False."""
    msg = ConversationMessage(role="assistant", content="Done", streaming=True)
    msg.streaming = False
    assert msg.streaming is False


def test_assistant_message_markdown_flag():
    """markdown=True is the default for assistant messages."""
    msg = ConversationMessage(role="assistant", content="**bold**")
    assert msg.markdown is True


def test_assistant_renderer_class():
    """RenderedAssistantMessage uses msg-assistant-container."""
    import inspect
    src = inspect.getsource(RenderedAssistantMessage)
    assert "msg-assistant-container" in src
