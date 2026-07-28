"""Phase 6.3 — Samaktha TUI Command Palette.

VS Code style command palette for searching and executing slash commands.
"""

from typing import Callable, List

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

from app.tui.commands import CommandRegistry


class CommandPalette(ModalScreen[str]):
    """Modal screen for fuzzy searching and executing commands."""

    DEFAULT_CSS = """
    CommandPalette {
        align: center middle;
        background: rgba(0, 0, 0, 0.8);
    }
    #palette-dialog {
        width: 60;
        height: 20;
        background: #0D0D0D;
        border: solid #2A2A2A;
        padding: 1 2;
    }
    #palette-input {
        background: #000000;
        border: none;
        border-bottom: solid #FF8C00;
        margin-bottom: 1;
        padding: 0;
    }
    #palette-input:focus {
        border-bottom: solid #00C96E;
    }
    """

    def __init__(self, registry: CommandRegistry, **kwargs):
        super().__init__(**kwargs)
        self.registry = registry
        self._all_commands = self.registry.get_all()

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-dialog"):
            yield Input(placeholder="Search commands...", id="palette-input")
            yield OptionList(id="palette-options")

    def on_mount(self) -> None:
        self.query_one("#palette-input", Input).focus()
        self._update_options("")

    def _update_options(self, query: str) -> None:
        options_list = self.query_one("#palette-options", OptionList)
        options_list.clear_options()
        
        query = query.lower()
        for cmd in self._all_commands:
            # Simple substring search
            if query in cmd.name or query in cmd.description.lower() or any(query in a for a in cmd.aliases):
                options_list.add_option(Option(f"/{cmd.name} - {cmd.description}", id=cmd.name))

    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_options(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        options_list = self.query_one("#palette-options", OptionList)
        if options_list.option_count > 0:
            # Submit the first option if they hit enter in the input
            # Default to index 0. Note: OptionList uses an highlighted index internally
            # but we'll just grab the id of the first item for now or highlighted.
            # Easiest way is to dismiss with the current highlighted option's ID
            if options_list.highlighted is not None:
                option = options_list.get_option_at_index(options_list.highlighted)
                self.dismiss(f"/{option.id}")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(f"/{event.option.id}")

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss()
