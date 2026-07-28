"""Phase 6.5 — Samaktha In-TUI Notification Widget.

Lightweight toast-style notification banners that appear inside the TUI
and auto-dismiss after a configured delay.
Pure presentation. No backend calls.
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Label


class NotificationKind(str, Enum):
    SUCCESS  = "success"
    WARNING  = "warning"
    ERROR    = "error"
    INFO     = "info"


_KIND_STYLE: dict[NotificationKind, tuple[str, str]] = {
    NotificationKind.SUCCESS: ("✔", "#00C96E"),
    NotificationKind.WARNING: ("⚠", "#FFB300"),
    NotificationKind.ERROR:   ("✖", "#FF4040"),
    NotificationKind.INFO:    ("ℹ", "#FF8C00"),
}


class NotificationBanner(Widget):
    """A single auto-dismissing notification banner."""

    DEFAULT_CSS = """
    NotificationBanner {
        height: 1;
        padding: 0 2;
        margin-bottom: 0;
        opacity: 1.0;
    }
    NotificationBanner.success { background: #003319; }
    NotificationBanner.warning { background: #2A2000; }
    NotificationBanner.error   { background: #330000; }
    NotificationBanner.info    { background: #1A0E00; }
    """

    def __init__(
        self,
        message: str,
        kind: NotificationKind = NotificationKind.INFO,
        duration: float = 4.0,
        **kwargs,
    ):
        super().__init__(classes=kind.value, **kwargs)
        self._message = message
        self._kind = kind
        self._duration = duration

    def compose(self) -> ComposeResult:
        icon, color = _KIND_STYLE.get(self._kind, ("ℹ", "#FF8C00"))
        yield Label(f"[{color}]{icon}[/]  {self._message}")

    async def on_mount(self) -> None:
        """Auto-dismiss after duration."""
        await asyncio.sleep(self._duration)
        await self.remove()


class NotificationHost(Vertical):
    """Container that stacks active NotificationBanners.
    
    Widgets can call `notify_tui(message, kind)` on this host to show a banner.
    """

    DEFAULT_CSS = """
    NotificationHost {
        height: auto;
        max-height: 5;
        dock: bottom;
        background: transparent;
    }
    """

    def compose(self) -> ComposeResult:
        yield from ()

    def notify_tui(
        self,
        message: str,
        kind: NotificationKind = NotificationKind.INFO,
        duration: float = 4.0,
    ) -> None:
        """Show a new notification banner."""
        self.mount(NotificationBanner(message=message, kind=kind, duration=duration))
