"""Tests for Phase 6.9 — Terminal UX Polish."""

import pytest
from app.tui.theme import SAMAKTHA_ORANGE, SAMAKTHA_BLACK, SAMAKTHA_TEXT, SAMAKTHA_DIM
from app.tui.feedback import AgentPipelineWidget
from app.tui.conversation import ConversationWelcome
from app.tui.renderer import RenderedAssistantMessage, RenderedUserMessage
from app.tui.models import ConversationMessage
from app.tui.session_browser import SessionBrowser


def test_theme_colors():
    """Verify theme consistency."""
    assert SAMAKTHA_ORANGE == "#FF8C00"
    assert SAMAKTHA_BLACK == "#000000"
    assert SAMAKTHA_TEXT == "#E8E8E8"
    assert SAMAKTHA_DIM == "#777777"


@pytest.mark.asyncio
async def test_loading_animation_timer():
    """Verify AgentPipelineWidget starts a timer for loading animation."""
    from textual.app import App, ComposeResult
    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield AgentPipelineWidget(id="pipeline")

    app = TestApp()
    async with app.run_test():
        pipeline = app.query_one("#pipeline", AgentPipelineWidget)
        assert getattr(pipeline, "_timer", None) is not None
        pipeline.stop_animation()
        assert pipeline._timer is None


@pytest.mark.asyncio
async def test_empty_conversation_welcome():
    """Verify minimal empty conversation welcome."""
    from textual.app import App, ComposeResult
    from textual.widgets import Label
    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield ConversationWelcome()

    app = TestApp()
    async with app.run_test():
        welcome = app.query_one(ConversationWelcome)
        title = welcome.query_one("#welcome-title", Label)
        assert "Ready" in str(title.render())


@pytest.mark.asyncio
async def test_markdown_code_copy_stub():
    """Verify renderer detects code blocks and displays copy stub."""
    from textual.app import App, ComposeResult
    from textual.widgets import Label
    
    msg = ConversationMessage(role="assistant", content="```python\nprint()\n```", streaming=False)
    
    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield RenderedAssistantMessage(msg)

    app = TestApp()
    async with app.run_test():
        widget = app.query_one(RenderedAssistantMessage)
        stub = widget.query_one("#code-copy-stub", Label)
        assert "Copy Available" in str(stub.render())


def test_session_browser_categories():
    """Verify session browser builds correctly."""
    class DummySessionManager:
        _active_sessions = {"test1": ..., "test2": ...}
        _archived_sessions = {"arch1": ...}
        
    browser = SessionBrowser(session_manager=DummySessionManager())
    browser._build_items()
    
    types = [k for _, _, k in browser._all_items]
    assert "current" in types
    assert "recent" in types
    assert "archived" in types
