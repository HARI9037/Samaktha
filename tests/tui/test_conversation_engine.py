"""Tests for Phase 6.6B Conversation Engine Core."""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Label

from app.tui.models import ConversationMessage
from app.tui.renderer import ConversationRenderer, RenderedUserMessage, RenderedAssistantMessage, RenderedErrorMessage, RenderedToolMessage

def test_conversation_message_defaults():
    msg = ConversationMessage(role="user", content="Hello")
    assert msg.role == "user"
    assert msg.content == "Hello"
    assert msg.streaming is False
    assert msg.error is False
    assert msg.markdown is True

def test_renderer_creates_user_message():
    msg = ConversationMessage(role="user", content="Test")
    widget = ConversationRenderer.render(msg)
    assert isinstance(widget, RenderedUserMessage)
    assert widget.message == msg

def test_renderer_creates_assistant_message():
    msg = ConversationMessage(role="assistant", content="Test")
    widget = ConversationRenderer.render(msg)
    assert isinstance(widget, RenderedAssistantMessage)
    assert widget.message == msg

def test_renderer_routes_structured_tool_output_to_tool_message():
    msg = ConversationMessage(
        role="tool",
        action="list",
        content={
            "path": "C:/Users/user/Desktop",
            "items": [{"name": "Folder", "type": "folder", "size": 0}],
            "count": 1,
        },
    )

    widget = ConversationRenderer.render(msg)

    assert isinstance(widget, RenderedToolMessage)
    assert not isinstance(widget, RenderedAssistantMessage)


@pytest.mark.asyncio
async def test_directory_tool_message_renders_listing_labels():
    msg = ConversationMessage(
        role="tool",
        action="list",
        content={
            "path": "Desktop",
            "items": [
                {"name": "Folder", "type": "folder", "size": 0},
                {"name": "File.pdf", "type": "file", "size": 2048},
            ],
            "count": 2,
        },
    )

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield RenderedToolMessage(msg)

    app = TestApp()
    async with app.run_test():
        labels = [str(label.render()) for label in app.query(Label)]

    rendered = "\n".join(labels)
    assert "Desktop" in rendered
    assert "Folder" in rendered
    assert "File.pdf" in rendered

def test_renderer_creates_error_message():
    msg = ConversationMessage(role="error", content="Test", error=True)
    widget = ConversationRenderer.render(msg)
    assert isinstance(widget, RenderedErrorMessage)
    assert widget.message == msg
