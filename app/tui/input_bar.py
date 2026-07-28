"""Phase 6.5 Polish — Samaktha TUI Input Bar.

Bottom-row prompt area. Captures user input and dispatches to AgentRuntime.
"""

from __future__ import annotations

from typing import Callable

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import TextArea, Label
from textual.events import Key
from textual.message import Message


class ChatInputArea(TextArea):
    """Custom TextArea to support Enter to submit and Shift+Enter for newline."""
    
    class Submitted(Message):
        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    async def _on_key(self, event: Key) -> None:
        if event.key == "enter":
            event.prevent_default()
            text = self.text.strip()
            if text:
                self.post_message(self.Submitted(text))
        elif event.key == "shift+enter":
            event.prevent_default()
            self.insert("\n")


class InputBar(Widget):
    """Single-row prompt at the bottom of the screen."""

    def __init__(
        self,
        on_submit: Callable[[str], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._on_submit = on_submit

    def compose(self) -> ComposeResult:
        with Horizontal(id="input-bar"):
            yield Label("❯", id="input-prompt")
            yield ChatInputArea(
                id="user-input",
                show_line_numbers=False,
            )

    def on_chat_input_area_submitted(self, event: ChatInputArea.Submitted) -> None:
        """Called when the user presses Enter."""
        text = event.text
        if not text:
            return
        
        # clear input
        ta = self.query_one("#user-input", ChatInputArea)
        ta.text = ""
        
        if self._on_submit:
            self._on_submit(text)

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the input field (while streaming)."""
        inp = self.query_one("#user-input", ChatInputArea)
        inp.disabled = not enabled
