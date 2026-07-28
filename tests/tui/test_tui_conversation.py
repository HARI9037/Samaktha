"""Tests for Phase 6.3 TUI Conversation panel (updated for 6.6B+ renderer model)."""

import pytest
from textual.app import App, ComposeResult
from app.tui.conversation import ConversationPanel
from app.tui.renderer import RenderedUserMessage, RenderedSystemMessage, RenderedAssistantMessage
from app.tui.models import ConversationMessage


class ConversationApp(App):
    def compose(self) -> ComposeResult:
        yield ConversationPanel(id="conv")


@pytest.mark.asyncio
async def test_conversation_panel_append_user():
    app = ConversationApp()
    async with app.run_test():
        conv = app.query_one("#conv", ConversationPanel)
        conv.append_user("Hello agent")
        msgs = conv.query(RenderedUserMessage)
        assert len(msgs) == 1
        assert msgs[0].message.content == "Hello agent"


@pytest.mark.asyncio
async def test_conversation_panel_append_system():
    app = ConversationApp()
    async with app.run_test():
        conv = app.query_one("#conv", ConversationPanel)
        conv.append_system("Executing...")
        msgs = conv.query(RenderedSystemMessage)
        assert len(msgs) == 1
        assert msgs[0].message.content == "Executing..."


def test_conversation_panel_markup_uses_theme_classes():
    """Verify user messages use the correct class."""
    import inspect
    src = inspect.getsource(RenderedUserMessage)
    assert "msg-user-container" in src


def test_conversation_panel_assistant_uses_theme_classes():
    """Verify assistant messages use the correct class."""
    import inspect
    src = inspect.getsource(RenderedAssistantMessage)
    assert "msg-assistant-container" in src


def test_conversation_panel_system_uses_theme_classes():
    """Verify system messages use the correct class."""
    import inspect
    src = inspect.getsource(RenderedSystemMessage)
    assert "msg-system" in src
