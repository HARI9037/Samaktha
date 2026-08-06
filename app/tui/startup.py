"""Phase 6.5 Polish — Samaktha TUI Startup Screen.

Premium OS-style boot sequence upgraded for Phase 11.1 with a launch banner:
version / session / provider / model / memory, plus "Type /help for commands".
"""

from __future__ import annotations

import asyncio
from typing import Callable, Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Label

from app.tui.theme import SAMAKTHA_DIM, SAMAKTHA_ORANGE, SAMAKTHA_SUCCESS, SAMAKTHA_BORDER

_BOOT_STEPS = [
    ("Initializing CAP...",       "CAP"),
    ("Initializing GAMBIT...",    "GAMBIT"),
    ("Initializing Runtime...",   "Runtime"),
    ("Loading Memory...",         "Memory"),
    ("Loading Session...",        "Session"),
    ("Checking Providers...",     "Providers"),
]

_STEP_DELAY = 0.06


def _resolve_value(value: object) -> str:
    """Resolve a row value to a plain string (callables evaluate once)."""
    return str(value() if callable(value) else value)


def _default_rows() -> list[tuple[str, str]]:
    return [
        ("Version", "0.x.x"),
        ("Session", "creating..."),
        ("Provider", "local"),
        ("Model", "—"),
        ("Memory", "Ready"),
    ]


class StartupScreen(Screen):
    """Premium animated boot sequence — feels like launching an OS."""

    def __init__(self, info: Optional[dict] = None, **kwargs) -> None:
        super().__init__(**kwargs)
        info = info or {}
        self._rows: list[tuple[str, str]] = [
            (label, _resolve_value(info.get(label.lower(), fallback)))
            for label, fallback in _default_rows()
        ]

    def compose(self) -> ComposeResult:
        with Vertical(id="startup-outer"):
            yield Label(f"[{SAMAKTHA_BORDER}]{'=' * 60}[/]")
            with Vertical(id="startup-brand-box"):
                yield Label("🔥  SAMAKTHA", id="startup-name")
                yield Label("Local AI Operating System", id="startup-tagline")
            yield Label(f"[{SAMAKTHA_BORDER}]{'-' * 60}[/]")
            with Vertical(id="startup-info-box"):
                for label, value in self._rows:
                    yield Label(f"{label}:", id=f"startup-{label.lower()}-label", classes="startup-row-label")
                    yield Label(f"{value}", id=f"startup-{label.lower()}-value", classes="startup-row-value")
            yield Label(f"[{SAMAKTHA_BORDER}]{'-' * 60}[/]")
            yield Label("◈ Agent Online", id="startup-ready")
            yield Label("Type /help for commands", id="startup-help")
            yield Label(f"[{SAMAKTHA_BORDER}]{'=' * 60}[/]")

    async def on_mount(self) -> None:
        await asyncio.sleep(0.3)
        for label, value in self._rows:
            label_widget = self.query_one(f"#startup-{label.lower()}-label", Label)
            value_widget = self.query_one(f"#startup-{label.lower()}-value", Label)
            value_widget.update(f"[{SAMAKTHA_SUCCESS}]✓[/] {value}")
            label_widget.add_class("startup-row-done")
            await asyncio.sleep(_STEP_DELAY)

        ready = self.query_one("#startup-ready", Label)
        ready.styles.display = "block"
        help_label = self.query_one("#startup-help", Label)
        help_label.styles.display = "block"
        await asyncio.sleep(0.6)
        self.app.switch_screen("main")
