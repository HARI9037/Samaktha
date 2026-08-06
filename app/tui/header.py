"""Phase 6.5 Polish — Samaktha TUI Header.

Redesigned header: 🔥 Samaktha | Local AI Operating System
Mascot sits on the left.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Label
from app.tui.mascot import MascotWidget



class SamakthaHeader(Widget):
    """Top-left product identity with the temporary fire mark."""

    def compose(self) -> ComposeResult:
        # We rely on CSS defined in theme.py, particularly #header, #header-mascot-cell, #header-text-cell
        with Horizontal(id="header"):
            with Vertical(id="header-mascot-cell"):
                yield MascotWidget(id="header-mascot")
            with Vertical(id="header-text-cell"):
                yield Label("Samaktha", id="header-title")
                yield Label("Local AI Operating System", id="header-subtitle")
