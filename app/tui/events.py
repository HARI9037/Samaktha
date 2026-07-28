"""Phase 6.2 — Samaktha TUI Event Indicator Strip.

Compact single-row strip lighting up individual event dots as AgentEvents arrive.
Dots dim automatically after a brief display period.
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label

from app.agent.models import AgentEvent
from app.tui.theme import SAMAKTHA_DIM, SAMAKTHA_ORANGE

# Map each trackable event to a short display label
_EVENT_LABELS: dict[AgentEvent, str] = {
    AgentEvent.PLAN_STARTED:   "PLAN▸",
    AgentEvent.PLAN_FINISHED:  "PLAN✓",
    AgentEvent.TOOL_STARTED:   "TOOL▸",
    AgentEvent.TOOL_FINISHED:  "TOOL✓",
    AgentEvent.STREAM_STARTED: "STRM▸",
    AgentEvent.STREAM_FINISHED:"STRM✓",
    AgentEvent.MEMORY_UPDATED: "MEM↑ ",
}

# Dim-after duration in seconds
_FLASH_DURATION = 1.5


class AgentEventDisplay(Widget):
    """Single-row event indicator strip. Lights up on AgentEvent, dims after timeout."""

    DEFAULT_CSS = """
    AgentEventDisplay {
        height: 1;
        background: #000000;
        border-bottom: solid #2A2A2A;
        padding: 0 2;
        layout: horizontal;
        align: left middle;
    }
    """

    def compose(self) -> ComposeResult:
        for event, label in _EVENT_LABELS.items():
            yield Label(
                f"[{SAMAKTHA_DIM}]{label}[/]",
                id=f"evt-{event.value}",
                classes="event-dot",
            )

    def flash_event(self, event: AgentEvent) -> None:
        """Light up the matching dot for FLASH_DURATION seconds."""
        label_str = _EVENT_LABELS.get(event)
        if label_str is None:
            return
        dot_id = f"evt-{event.value}"
        try:
            dot = self.query_one(f"#{dot_id}", Label)
        except Exception:
            return

        dot.update(f"[bold {SAMAKTHA_ORANGE}]{label_str}[/]")
        asyncio.get_event_loop().call_later(
            _FLASH_DURATION,
            lambda: dot.update(f"[{SAMAKTHA_DIM}]{label_str}[/]"),
        )
