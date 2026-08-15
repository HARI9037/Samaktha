"""Regression tests for the P2.9-era TUI layout bug.

Two user-facing symptoms were traced to a single root cause: the
``StatusPanel`` widget is composed with ``id="voice-status-panel"`` but the
theme CSS targeted ``#status-panel``, so the panel had no height rule and its
inner ``Horizontal`` (default ``height: 1fr``) expanded it to fill the whole
screen. That crushed the conversation to ~2 rows and pushed it off-screen,
producing a large empty gap and making responses render invisibly.

These tests pin the fix: the CSS must match the widget id and the conversation
must keep its ``1fr`` space so submitted responses are visible.
"""

import asyncio
import inspect

import pytest
from textual.app import App

from app.tui.app import MainScreen
from app.tui.conversation import ConversationPanel
from app.tui.header import SamakthaHeader
from app.tui.status_panel import StatusPanel
from app.tui.theme import SAMAKTHA_CSS


class _FakeRuntime:
    """Minimal runtime exposing handle_message as an item stream."""

    def __init__(self, items=None):
        self._items = items or []

    async def _gen(self):
        for item in self._items:
            yield item

    def handle_message(self, session_id, text):
        return self._gen()

    def resume(self, session_id, task_id, updates):
        return self._gen()


class _Host(App):
    """Faithful harness: app-level SAMAKTHA_CSS + pushed main screen."""

    CSS = SAMAKTHA_CSS

    def __init__(self, runtime=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._rt = runtime

    def on_mount(self) -> None:
        main = MainScreen(runtime=self._rt, name="main")
        self.install_screen(main, "main")
        self.push_screen("main")


async def _settle(pilot, n: int = 15, dt: float = 0.02) -> None:
    for _ in range(n):
        await pilot.pause()
        await asyncio.sleep(dt)


# ---------------------------------------------------------------------------
# Source guard: CSS selectors and widget id must stay in sync
# ---------------------------------------------------------------------------


def test_voice_status_panel_css_matches_widget_id():
    assert "#voice-status-panel" in SAMAKTHA_CSS
    assert "#voice-status-panel > Horizontal" in SAMAKTHA_CSS
    src = inspect.getsource(MainScreen.compose)
    assert 'id="voice-status-panel"' in src
    assert 'id="status-panel"' not in src


def test_status_panel_is_a_single_row_strip():
    assert "height: 1;" in SAMAKTHA_CSS.split("#voice-status-panel {", 1)[1]


# ---------------------------------------------------------------------------
# Behavioral: layout must give the conversation its 1fr space
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_main_layout_conversation_keeps_visible_space():
    async with _Host(runtime=None).run_test(size=(120, 40)) as pilot:
        await _settle(pilot)
        screen = pilot.app.screen

        conv = screen.query_one("#conversation", ConversationPanel)
        status = screen.query_one("#voice-status-panel", StatusPanel)
        header = screen.query_one(SamakthaHeader)

        # The conversation must own the middle of the screen (not 2 rows).
        assert conv.region.height >= 20
        # The voice status panel is a thin transient strip (was the full 40 rows).
        assert status.region.height == 1
        # The header starts at the top of the screen (was scrolled off at y=-15).
        assert header.region.y == 0
        # Conversation sits above the status strip, never overlapping it.
        assert conv.region.bottom <= status.region.y


@pytest.mark.asyncio
async def test_submitted_response_is_rendered_into_visible_conversation():
    runtime = _FakeRuntime(
        [
            {"type": "provider", "content": "Hello "},
            {"type": "provider", "content": "Samaktha"},
        ]
    )
    async with _Host(runtime=runtime).run_test(size=(120, 40)) as pilot:
        await _settle(pilot)
        screen = pilot.app.screen
        conv = screen.query_one("#conversation", ConversationPanel)

        screen._handle_user_input("hi")
        for _ in range(60):
            await pilot.pause()
            await asyncio.sleep(0.01)

        assert any(
            m.role == "assistant" and m.content == "Hello Samaktha"
            for m in conv.messages
        )
        # The response lives inside a conversation large enough to see it.
        assert conv.region.height >= 20
        # Input is restored after the stream ends.
        assert screen.query_one("#user-input").disabled is False
