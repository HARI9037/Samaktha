"""Phase 6.3 — Samaktha TUI Tool Execution Panel.

Modal tracking live tool execution queues, success/failures, and durations.
"""

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, DataTable

from app.tui.theme import SAMAKTHA_ORANGE


class ToolExecutionPanel(ModalScreen):
    """Modal screen displaying tool executions."""

    DEFAULT_CSS = """
    ToolExecutionPanel {
        align: center middle;
        background: rgba(0, 0, 0, 0.8);
    }
    #tool-dialog {
        width: 80%;
        height: 80%;
        background: #0D0D0D;
        border: solid #2A2A2A;
        padding: 1 2;
    }
    #tool-title {
        color: #FF8C00;
        text-style: bold;
        margin-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="tool-dialog"):
            yield Label("Tool Execution Panel", id="tool-title")
            table = DataTable(id="tool-table")
            table.add_columns("Tool Name", "Status", "Duration", "Retries")
            # Stub data for visualization
            table.add_row("web_search", "[green]Success[/green]", "1.2s", "0")
            table.add_row("read_file", "[green]Success[/green]", "0.05s", "0")
            yield table

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss()
