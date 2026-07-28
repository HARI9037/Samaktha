"""Phase 6.5 Polish — Samaktha TUI Startup Screen.

Premium OS-style boot sequence.
"""

from __future__ import annotations

import asyncio

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

_STEP_DELAY = 0.15

class StartupScreen(Screen):
    """Premium animated boot sequence — feels like launching an OS."""

    def compose(self) -> ComposeResult:
        with Vertical(id="startup-outer"):
            yield Label(f"[{SAMAKTHA_BORDER}]{'=' * 60}[/]")
            with Vertical(id="startup-brand-box"):
                yield Label("🔥  SAMAKTHA", id="startup-name")
                yield Label("Local AI Operating System", id="startup-tagline")
            yield Label(f"[{SAMAKTHA_BORDER}]{'-' * 60}[/]")
            with Vertical(id="startup-steps-box"):
                for label_text, key in _BOOT_STEPS:
                    yield Label(
                        f"{label_text:<40}  [dim]pending[/]",
                        id=f"step-{key.lower()}",
                        classes="startup-step-pending",
                    )
            yield Label(f"[{SAMAKTHA_BORDER}]{'-' * 60}[/]")
            yield Label("◈ Agent Online", id="startup-ready")
            yield Label(f"[{SAMAKTHA_BORDER}]{'=' * 60}[/]")

    async def on_mount(self) -> None:
        await asyncio.sleep(0.3)
        for label_text, key in _BOOT_STEPS:
            label = self.query_one(f"#step-{key.lower()}", Label)
            label.update(f"{label_text:<40}  [{SAMAKTHA_SUCCESS}]✓[/]")
            label.remove_class("startup-step-pending")
            label.add_class("startup-step-done")
            await asyncio.sleep(_STEP_DELAY)

        ready = self.query_one("#startup-ready", Label)
        ready.styles.display = "block"
        await asyncio.sleep(0.8)
        self.app.switch_screen("main")
