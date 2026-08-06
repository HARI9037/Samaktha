"""Phase 6.7 — Samaktha TUI Conversation Panel.

Scrollable panel rendering the full message history using Markdown.
Uses the ConversationRenderer + ConversationMessage model from 6.6B.
Agent feedback pipeline (TypingIndicator → AgentPipelineWidget) from 6.7.
"""

from __future__ import annotations

from typing import Any, Optional

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Label

from app.tui.theme import SAMAKTHA_DIM, SAMAKTHA_ORANGE, SAMAKTHA_TEXT
from app.tui.models import ConversationMessage
from app.tui.renderer import ConversationRenderer, RenderedMessage
from app.tui.feedback import AgentPipelineWidget


class ConversationWelcome(Widget):
    """Branded empty state shown before the first conversation."""

    def compose(self) -> ComposeResult:
        with Vertical(id="welcome-card"):
            yield Label("🔥\nSamaktha\nLocal AI Operating System\n\nReady.", id="welcome-title")



class ConversationPanel(VerticalScroll):
    """Scrollable conversation display. Supports streaming appends."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.messages: list[ConversationMessage] = []
        self._current_assistant_msg: Optional[ConversationMessage] = None
        self._active_widget: Optional[RenderedMessage] = None
        self._pipeline: Optional[AgentPipelineWidget] = None
        self._bus: Any = None

    def attach_bus(self, bus: Any) -> None:
        """Store the RuntimeEventBus and pass to children if needed."""
        self._bus = bus

    def compose(self) -> ComposeResult:
        yield ConversationWelcome()

    def _dismiss_welcome(self) -> None:
        try:
            self.query_one("#welcome-card").remove()
        except Exception:
            pass

    def reset(self) -> None:
        """Clear the transcript and restore the intentional empty state."""
        self.messages.clear()
        self.query("RenderedMessage, AgentPipelineWidget").remove()
        self._pipeline = None
        self.mount(ConversationWelcome())

    def _append_message(self, msg: ConversationMessage) -> RenderedMessage:
        self._dismiss_welcome()
        self.messages.append(msg)
        widget = ConversationRenderer.render(msg)
        self.mount(widget)
        return widget

    def append_user(self, content: str) -> None:
        """Append a user message turn."""
        msg = ConversationMessage(role="user", content=content)
        self._append_message(msg)
        self.scroll_end(animate=False)

    # ------------------------------------------------------------------
    # Agent pipeline (replaces TypingIndicator)
    # ------------------------------------------------------------------

    def show_typing_indicator(self) -> None:
        """Show the agent pipeline at the default 'thinking' stage."""
        self._dismiss_welcome()
        if not self._pipeline:
            self._pipeline = AgentPipelineWidget()
            self.mount(self._pipeline)
            self.scroll_end(animate=False)
        else:
            self._pipeline.advance("thinking")

    def update_typing_indicator(self, text: str) -> None:
        """Compatibility shim: map legacy text labels to pipeline stages."""
        _map = {
            "Planning...": "planning",
            "Executing...": "executing",
            "Generating...": "generating",
            "🧠 Searching memory...": "memory",
        }
        stage = _map.get(text, "thinking")
        if self._pipeline:
            self._pipeline.advance(stage)

    def advance_pipeline(self, stage: str) -> None:
        """Advance the pipeline to a named stage key."""
        if self._pipeline:
            self._pipeline.advance(stage)

    def hide_typing_indicator(self) -> None:
        """Remove the agent pipeline widget."""
        if self._pipeline:
            self._pipeline.remove()
            self._pipeline = None

    # Alias for clarity
    hide_pipeline = hide_typing_indicator

    # ------------------------------------------------------------------
    # Agent feedback helpers
    # ------------------------------------------------------------------

    def append_tool_activity(self, tool_name: str, done: bool = False) -> None:
        """Append a compact tool activity line."""
        self._dismiss_welcome()
        widget = ConversationRenderer.render_tool(tool_name, done)
        self.mount(widget)
        at_bottom = self.scroll_y >= (self.max_scroll_y - 2)
        if at_bottom:
            self.scroll_end(animate=False)

    def append_tool_output(self, content: Any, action: str | None = None, show_header: bool = False) -> None:
        """Append the raw output of a tool (e.g. directory listing)."""
        self._dismiss_welcome()
        msg = ConversationMessage(role="tool", content=content, action=action, show_header=show_header)
        self._append_message(msg)
        self.scroll_end(animate=False)

    def append_memory_feedback(self, count: int) -> None:
        """Append a memory retrieval feedback line."""
        label = f"🧠 Retrieved {count} relevant memor{'y' if count == 1 else 'ies'}"
        msg = ConversationMessage(role="system", content=label, markdown=False)
        self._append_message(msg)
        self.scroll_end(animate=False)

    def append_approval_request(self, task_id: str | None = None, pause_data: dict | None = None) -> None:
        """Appends an inline warning for an approval request."""
        self._dismiss_welcome()
        widget = ConversationRenderer.render_approval(task_id, pause_data)
        if self._bus and hasattr(widget, "attach_bus"):
            widget.attach_bus(self._bus)
        self.mount(widget)
        self.app.call_later(self.scroll_end, animate=False)
        
    def append_attachment(self, attachment: "Attachment") -> None:
        """Appends a file attachment card to the conversation."""
        from app.tui.renderer import AttachmentRenderer
        self._dismiss_welcome()
        widget = AttachmentRenderer.render(attachment)
        self.mount(widget)
        self.scroll_end(animate=False)

    def append_assistant_start(self) -> None:
        """Begin an assistant message (streaming mode)."""
        msg = ConversationMessage(role="assistant", content="", streaming=True)
        self._current_assistant_msg = msg
        self._active_widget = self._append_message(msg)
        self.scroll_end(animate=False)

    def append_stream_token(self, token: str) -> None:
        """Append a single streaming token to the current assistant turn."""
        if self._current_assistant_msg and self._active_widget:
            at_bottom = self.scroll_y >= (self.max_scroll_y - 2)
            self._current_assistant_msg.content += token
            self._active_widget.update_from_model()
            if at_bottom:
                self.scroll_end(animate=False)

    def append_assistant_end(self) -> None:
        """Finalize the current assistant turn."""
        if self._current_assistant_msg and self._active_widget:
            self._current_assistant_msg.streaming = False
            self._active_widget.update_from_model()
            self._current_assistant_msg = None
            self._active_widget = None
            self.scroll_end(animate=False)

    def append_system(self, content: str) -> None:
        """Append a system / tool message in dim style."""
        msg = ConversationMessage(role="system", content=content)
        self._append_message(msg)
        self.scroll_end(animate=False)

    def append_error(self, content: str) -> None:
        """Append an error message."""
        msg = ConversationMessage(role="error", content=content, error=True)
        self._append_message(msg)
        self.scroll_end(animate=False)
