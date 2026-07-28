"""Phase 6.3 — Samaktha TUI Plan Inspector.

Modal tree visualization of the current ExecutionPlan.
"""

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Tree

from app.tui.theme import SAMAKTHA_ORANGE


class PlanInspector(ModalScreen):
    """Modal screen displaying current execution plan."""

    DEFAULT_CSS = """
    PlanInspector {
        align: center middle;
        background: rgba(0, 0, 0, 0.8);
    }
    #plan-dialog {
        width: 80%;
        height: 80%;
        background: #0D0D0D;
        border: solid #2A2A2A;
        padding: 1 2;
    }
    #plan-title {
        color: #FF8C00;
        text-style: bold;
        margin-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="plan-dialog"):
            yield Label("Plan Inspector", id="plan-title")
            tree = Tree("Current Execution Plan")
            tree.root.expand()
            # Stub data for visualization
            task1 = tree.root.add("Task 1: Search Knowledge Base")
            task1.add_leaf("Assigned Agent: Researcher")
            task1.add_leaf("Status: [green]Completed[/green]")
            
            task2 = tree.root.add("Task 2: Compile Report")
            task2.add_leaf("Assigned Agent: Writer")
            task2.add_leaf("Status: [orange3]Pending[/orange3]")
            yield tree

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss()
