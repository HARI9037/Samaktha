"""Phase 6.5 Polish — Samaktha TUI Input Bar.

Bottom-row prompt area. Captures user input and dispatches to AgentRuntime.
Phase 11.1 adds per-session Up/Down history navigation and Tab completion.
"""

from __future__ import annotations

from typing import Callable, List, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import TextArea, Label
from textual.events import Key
from textual.message import Message

from app.tui.command_history import CommandCompleter, ShellHistory


class ChatInputArea(TextArea):
    """Custom TextArea with Enter to submit, Shift+Enter for newline,
    Up/Down for per-session history, and Tab for slash-command completion.
    """

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    def __init__(
        self,
        history: Optional[ShellHistory] = None,
        commands: Optional[List[str]] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._history = history or ShellHistory()
        self._completer = CommandCompleter(commands)

    def set_history(self, history: ShellHistory) -> None:
        """Swap the history buffer (e.g. when the active session changes)."""
        self._history = history

    def set_commands(self, commands: List[str]) -> None:
        self._completer = CommandCompleter(commands)

    def push_history(self, text: str) -> None:
        """Record a submitted line into the active session history."""
        self._history.push(text)

    def _set_text_cursor_end(self, value: str) -> None:
        self.text = value
        lines = self.lines or [""]
        row = max(0, len(lines) - 1)
        col = len(lines[row]) if lines else 0
        self.move_cursor((row, col))

    async def _on_key(self, event: Key) -> None:
        if event.key == "enter":
            event.prevent_default()
            text = self.text.strip()
            if text:
                self.post_message(self.Submitted(text))
        elif event.key == "shift+enter":
            event.prevent_default()
            self.insert("\n")
        elif event.key == "up":
            event.prevent_default()
            previous = self._history.back(self.text)
            if previous is not None:
                self._set_text_cursor_end(previous)
        elif event.key == "down":
            event.prevent_default()
            next_text = self._history.forward(self.text)
            if next_text is not None:
                self._set_text_cursor_end(next_text)
        elif event.key == "tab":
            completed = self._completer.complete(self.text)
            if completed is not None:
                event.prevent_default()
                self._set_text_cursor_end(completed)


class InputBar(Widget):
    """Single-row prompt at the bottom of the screen."""

    def __init__(
        self,
        on_submit: Callable[[str], None] | None = None,
        history: Optional[ShellHistory] = None,
        commands: Optional[List[str]] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._on_submit = on_submit
        self._history = history
        self._commands = commands

    def compose(self) -> ComposeResult:
        with Horizontal(id="input-bar"):
            yield Label("❯", id="input-prompt")
            yield ChatInputArea(
                id="user-input",
                show_line_numbers=False,
                history=self._history,
                commands=self._commands,
            )

    def on_chat_input_area_submitted(self, event: ChatInputArea.Submitted) -> None:
        """Called when the user presses Enter."""
        text = event.text
        if not text:
            return
        
        # clear input
        ta = self.query_one("#user-input", ChatInputArea)
        ta.text = ""
        ta.push_history(text)
        
        if self._on_submit:
            self._on_submit(text)

    def set_session_history(self, history: ShellHistory) -> None:
        """Attach a specific session's history buffer to the input area."""
        self.query_one("#user-input", ChatInputArea).set_history(history)

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the input field (while streaming)."""
        inp = self.query_one("#user-input", ChatInputArea)
        inp.disabled = not enabled
