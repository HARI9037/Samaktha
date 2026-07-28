"""Phase 6.5 — Samaktha TUI Memory Awareness Panel.

Upgraded inspector showing retrieved memory context items with labels.
When AgentRuntime retrieves memory, this panel is populated with the context.
Pure read-only display — no backend modification.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label

from app.tui.theme import SAMAKTHA_DIM, SAMAKTHA_ORANGE, SAMAKTHA_SUCCESS, SAMAKTHA_TEXT


class MemoryInspector(ModalScreen):
    """Premium memory inspector showing recent retrieved context items."""

    DEFAULT_CSS = """
    MemoryInspector {
        align: center middle;
        background: rgba(0, 0, 0, 0.85);
    }
    #memory-dialog {
        width: 80%;
        height: 80%;
        background: #0D0D0D;
        border: solid #2A2A2A;
        padding: 1 2;
    }
    #memory-title {
        color: #FF8C00;
        text-style: bold;
        margin-bottom: 1;
    }
    #memory-subtitle {
        color: #4A4A4A;
        margin-bottom: 1;
    }
    .memory-section-header {
        color: #FF8C00;
        text-style: bold;
        margin-top: 1;
        margin-bottom: 0;
    }
    .memory-item {
        color: #E8E8E8;
        padding-left: 2;
        margin-bottom: 0;
    }
    .memory-item-dim {
        color: #4A4A4A;
        padding-left: 4;
    }
    #memory-hint {
        color: #4A4A4A;
        margin-top: 1;
    }
    """

    def __init__(self, memory_items: list[dict] | None = None, **kwargs):
        super().__init__(**kwargs)
        # memory_items is injected by the TUI dispatcher (presentation data only)
        self._memory_items: list[dict] = memory_items or []

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="memory-dialog"):
            yield Label("◈  Memory Inspector", id="memory-title")
            yield Label("Read-only view of retrieved context", id="memory-subtitle")
            
            if not self._memory_items:
                # Show illustrative demo data when no live data is injected
                yield Label("Recent Context:", classes="memory-section-header")
                for item in [
                    "CAP Architecture Guidelines",
                    "Previous Conversation Turn",
                    "Runtime Benchmark Results",
                    "GAMBIT Planning Patterns",
                ]:
                    yield Label(f"  [{SAMAKTHA_SUCCESS}]●[/]  {item}", classes="memory-item")
                
                yield Label("Long-term Memory:", classes="memory-section-header")
                for item in [
                    "User Preferences",
                    "Project Configuration",
                ]:
                    yield Label(f"  [{SAMAKTHA_DIM}]○[/]  {item}", classes="memory-item")
                    
                yield Label(
                    f"\n[{SAMAKTHA_DIM}](No live memory context — connect AgentRuntime for real data)[/]",
                    classes="memory-item-dim",
                )
            else:
                for chunk in self._memory_items:
                    source = chunk.get("source", "Memory")
                    content = chunk.get("content", "")[:120]
                    yield Label(f"[{SAMAKTHA_ORANGE}]► {source}[/]", classes="memory-section-header")
                    yield Label(f"  {content}…", classes="memory-item")

            yield Label("Esc  Close", id="memory-hint")

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss()
