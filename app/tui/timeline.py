"""Phase 6.3 — Samaktha Agent Event Timeline.

Displays chronological events such as Memory Retrieved, Plan Created, etc.
"""

from datetime import datetime

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import RichLog

from app.agent.models import AgentEvent
from app.tui.theme import SAMAKTHA_DIM, SAMAKTHA_TEXT


class TimelinePanel(Widget):
    """Scrollable, timestamped chronological log of agent events."""

    DEFAULT_CSS = """
    TimelinePanel {
        height: 1;
        display: none;
        background: #000000;
        border: solid #2A2A2A;
        padding: 0 1;
        margin: 1 2;
    }
    #timeline-log {
        background: #000000;
        scrollbar-color: #2A2A2A #000000;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._entries: list[tuple[str, str]] = []  # (timestamp, label)

    def compose(self) -> ComposeResult:
        yield RichLog(id="timeline-log", wrap=False, highlight=False, markup=True)

    def log_event(self, event: AgentEvent, data: dict) -> None:
        """Format and append an AgentEvent to the timeline."""
        log = self.query_one("#timeline-log", RichLog)
        
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        
        labels = {
            AgentEvent.PLAN_STARTED: "Plan Created",
            AgentEvent.PLAN_FINISHED: "Plan Finished",
            AgentEvent.TOOL_STARTED: "Tool Started",
            AgentEvent.TOOL_FINISHED: "Tool Finished",
            AgentEvent.STREAM_STARTED: "Streaming Started",
            AgentEvent.STREAM_FINISHED: "Streaming Finished",
            AgentEvent.MEMORY_UPDATED: "Memory Retrieved",
            AgentEvent.MODEL_SELECTED: "Provider Selected",
            AgentEvent.SESSION_CREATED: "Session Created",
            AgentEvent.USER_MESSAGE: "User Message Received",
            AgentEvent.ASSISTANT_MESSAGE: "Assistant Message Sent",
            AgentEvent.ERROR_OCCURRED: "Error Occurred",
        }
        
        label = labels.get(event, event.value)
        
        # Add summary data if useful
        extra = ""
        if event == AgentEvent.TOOL_STARTED:
            extra = f" ({data.get('tool', data.get('tasks', ''))})"
        elif event == AgentEvent.MEMORY_UPDATED:
            extra = f" (Items: {data.get('items_found', 0)})"
        elif event == AgentEvent.MODEL_SELECTED:
            extra = f" (Provider: {data.get('provider', 'unknown')})"
        elif event == AgentEvent.ERROR_OCCURRED:
            extra = f" (Reason: {data.get('reason', 'unknown')})"
            
        self._entries.append((timestamp, f"{label}{extra}"))
        entry = f"[{SAMAKTHA_DIM}]{timestamp}[/] [{SAMAKTHA_TEXT}]{label}{extra}[/]"
        log.write(entry)

    def get_entries(self) -> list[tuple[str, str]]:
        """Return a snapshot of (timestamp, label) pairs for inspector panels."""
        return list(self._entries)

