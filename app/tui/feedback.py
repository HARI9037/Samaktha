"""Phase 6.7 — Samaktha Agent Feedback Layer.

AgentPipelineWidget: live 5-stage progress indicator driven by AgentEvents.
AgentEventLog: in-memory chronological diagnostic log.

Pure presentation. Zero backend imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label


# ---------------------------------------------------------------------------
# Pipeline stage definitions
# ---------------------------------------------------------------------------

PIPELINE_STAGES: list[tuple[str, str]] = [
    ("thinking",   "🔥 Thinking..."),
    ("memory",     "🧠 Searching memory..."),
    ("planning",   "📋 Planning..."),
    ("executing",  "🔧 Executing tools..."),
    ("generating", "🤖 Generating response..."),
]

# stage_key → display label
_STAGE_LABELS: dict[str, str] = {k: v for k, v in PIPELINE_STAGES}


class AgentPipelineWidget(Widget):
    """Live 5-stage pipeline indicator shown while the agent is working.

    Advances through stages by calling advance(stage_key).
    Hidden automatically when generation begins.
    """

    DEFAULT_CSS = """
    AgentPipelineWidget {
        height: 1;
        padding: 0 0;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._current_stage = "thinking"
        self._frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._frame_idx = 0
        self._timer = None

    def compose(self) -> ComposeResult:
        yield Label(f"{self._frames[0]} {_STAGE_LABELS['thinking']}", classes="msg-system", id="pipeline-label")

    def on_mount(self) -> None:
        self._timer = self.set_interval(0.1, self._tick)

    def _tick(self) -> None:
        self._frame_idx = (self._frame_idx + 1) % len(self._frames)
        self._update_display()

    def advance(self, stage_key: str) -> None:
        """Advance to the named stage. Silently ignores unknown keys."""
        if stage_key not in _STAGE_LABELS:
            return
        self._current_stage = stage_key
        self._update_display()

    def _update_display(self) -> None:
        try:
            label_text = _STAGE_LABELS.get(self._current_stage, "...")
            frame = self._frames[self._frame_idx]
            # Replace fire emoji with frame if the label starts with it
            if label_text.startswith("🔥"):
                display_text = f"{frame} {label_text[2:]}"
            else:
                display_text = f"{frame} {label_text}"
            self.query_one("#pipeline-label", Label).update(display_text)
        except Exception:
            pass

    def stop_animation(self) -> None:
        if self._timer:
            self._timer.stop()
            self._timer = None


# ---------------------------------------------------------------------------
# In-memory event log (diagnostic only — not shown in the main UI)
# ---------------------------------------------------------------------------

@dataclass
class EventEntry:
    timestamp: str
    label: str
    data: dict = field(default_factory=dict)


_EVENT_LABELS: dict[str, str] = {
    "USER_MESSAGE":     "User Message",
    "PLAN_STARTED":     "Planning",
    "PLAN_FINISHED":    "Plan Complete",
    "TOOL_STARTED":     "Tool Execution",
    "TOOL_FINISHED":    "Tool Complete",
    "MODEL_SELECTED":   "Provider Selected",
    "STREAM_STARTED":   "Streaming",
    "STREAM_FINISHED":  "Response Complete",
    "MEMORY_UPDATED":   "Searching Memory",
    "SESSION_CREATED":  "Session Created",
    "ASSISTANT_MESSAGE":"Response Sent",
    "ERROR_OCCURRED":   "Error",
}


class AgentEventLog:
    """Chronological in-memory log of AgentEvent occurrences.

    Used for diagnostics and future inspector panels.
    Never displayed permanently in the conversation.
    """

    def __init__(self, max_entries: int = 200):
        self._entries: list[EventEntry] = []
        self._max = max_entries

    def record(self, event_value: str, data: dict) -> EventEntry:
        """Record an agent event. Returns the created entry."""
        entry = EventEntry(
            timestamp=datetime.now().strftime("%H:%M:%S"),
            label=_EVENT_LABELS.get(event_value, event_value),
            data=data,
        )
        self._entries.append(entry)
        if len(self._entries) > self._max:
            self._entries.pop(0)
        return entry

    def get_entries(self) -> list[EventEntry]:
        """Return a snapshot of all recorded entries."""
        return list(self._entries)

    def clear(self) -> None:
        self._entries.clear()
