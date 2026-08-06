"""Phase 21.2 — Truthful Runtime Status Bar.

A single-row Textual widget that reflects actual execution state by subscribing
to the RuntimeEventBus. It never polls, never guesses, and never fabricates
progress indicators. Every displayed string originates from a RuntimeEvent.

Architecture:
- StatusBar subscribes to RuntimeEventBus on attach.
- Every RuntimeEvent drives one of the transitions in _TRANSITIONS.
- A lightweight repaint timer (100 ms) updates only the elapsed duration string.
- The timer never modifies state; it only triggers a safe UI repaint.
- All state mutations are marshalled onto Textual's UI thread via post_message().
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label

from app.core.events import RuntimeEvent, RuntimeEventBus, RuntimeEventType


# ---------------------------------------------------------------------------
# Internal state machine stages
# ---------------------------------------------------------------------------

class _Stage(Enum):
    IDLE         = auto()
    CAP          = auto()
    GAMBIT       = auto()
    WORKFLOW     = auto()
    TOOL         = auto()
    PROVIDER     = auto()
    MEMORY       = auto()
    APPROVAL     = auto()
    FAILED       = auto()


# ---------------------------------------------------------------------------
# Textual Message: used to marshal event-bus callbacks onto the UI thread
# ---------------------------------------------------------------------------

class _RuntimeEventReceived(Message):
    """Carries a RuntimeEvent from the background callback to the UI thread."""

    def __init__(self, event: RuntimeEvent) -> None:
        super().__init__()
        self.runtime_event = event


# ---------------------------------------------------------------------------
# StatusBar widget
# ---------------------------------------------------------------------------

class StatusBar(Widget):
    """Single-row truthful execution status bar.

    Usage:
        bar = StatusBar(id="status-bar")
        # After mounting, attach a bus:
        bar.attach_bus(event_bus)

    The widget subscribes to ``RuntimeEventBus`` and reacts to every event.
    It owns NO execution state and makes NO calls into the runtime.
    """

    # The single reactive that drives render(). Changing this triggers a repaint.
    _display_text: reactive[str] = reactive("SAMAKTHA  |  Ready")

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        width: 1fr;
        padding: 0 2;
        background: #000000;
        color: #777777;
    }
    StatusBar Label {
        width: 1fr;
        height: 1;
        color: #777777;
    }
    StatusBar .status-active {
        color: #FFA733;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # Internal state — mutable only inside _apply_transition()
        self._stage: _Stage = _Stage.IDLE
        self._active_name: str = ""
        self._stage_start: float = 0.0
        self._sub_id: Optional[str] = None
        self._bus: Optional[RuntimeEventBus] = None
        # Duration refresh timer handle
        self._timer = None

    # ------------------------------------------------------------------
    # Widget lifecycle
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Label(self._display_text, id="status-bar-label")

    def on_mount(self) -> None:
        # Timer ticks every 100 ms — only repaints the duration text.
        # It never modifies state. It never transitions the machine.
        self._timer = self.set_interval(0.1, self._refresh_duration)

    def on_unmount(self) -> None:
        self._detach_bus()
        if self._timer is not None:
            self._timer.stop()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def attach_bus(self, bus: RuntimeEventBus) -> None:
        """Subscribe to a RuntimeEventBus.  Safe to call after mount."""
        self._detach_bus()
        self._bus = bus
        self._sub_id = bus.subscribe(self._on_runtime_event_callback)

    def detach_bus(self) -> None:
        """Unsubscribe from the current bus (e.g., when a session ends)."""
        self._detach_bus()

    # ------------------------------------------------------------------
    # Event-bus callback — runs in the asyncio event loop, NOT the UI thread
    # ------------------------------------------------------------------

    def _on_runtime_event_callback(self, event: RuntimeEvent) -> None:
        """Receive a RuntimeEvent from the bus and post it to the UI thread."""
        self.post_message(_RuntimeEventReceived(event))

    # ------------------------------------------------------------------
    # Textual message handler — runs on the UI thread
    # ------------------------------------------------------------------

    def on_runtime_event_received(self, message: _RuntimeEventReceived) -> None:
        """Process a RuntimeEvent that has arrived on the UI thread."""
        self._apply_transition(message.runtime_event)

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def _apply_transition(self, event: RuntimeEvent) -> None:
        """Transition the state machine based on the event type."""
        etype = event.data.event_type
        payload = event.data.payload or {}

        if etype == RuntimeEventType.CAP_STARTED:
            self._enter_stage(_Stage.CAP)

        elif etype == RuntimeEventType.GAMBIT_PLANNING_STARTED:
            self._enter_stage(_Stage.GAMBIT)

        elif etype == RuntimeEventType.WORKFLOW_SCHEDULED:
            self._enter_stage(_Stage.WORKFLOW)

        elif etype == RuntimeEventType.TASK_STARTED:
            # Remain WORKFLOW — no stage change
            if self._stage not in (_Stage.TOOL, _Stage.PROVIDER):
                self._enter_stage(_Stage.WORKFLOW)

        elif etype == RuntimeEventType.TOOL_STARTED:
            name = (
                payload.get("tool_name")
                or payload.get("tool")
                or payload.get("name")
                or "unknown"
            )
            self._active_name = name
            self._enter_stage(_Stage.TOOL)

        elif etype in (RuntimeEventType.TOOL_COMPLETED, RuntimeEventType.TOOL_FAILED):
            self._active_name = ""
            self._enter_stage(_Stage.WORKFLOW)

        elif etype == RuntimeEventType.PROVIDER_STARTED:
            name = (
                payload.get("provider_name")
                or payload.get("provider")
                or payload.get("name")
                or "unknown"
            )
            self._active_name = name
            self._enter_stage(_Stage.PROVIDER)

        elif etype in (RuntimeEventType.PROVIDER_COMPLETED, RuntimeEventType.PROVIDER_FAILED):
            self._active_name = ""
            self._enter_stage(_Stage.WORKFLOW)

        elif etype == RuntimeEventType.MEMORY_STARTED:
            self._enter_stage(_Stage.MEMORY)

        elif etype == RuntimeEventType.APPROVAL_REQUESTED:
            self._enter_stage(_Stage.APPROVAL)

        elif etype == RuntimeEventType.WORKFLOW_FAILED:
            self._enter_stage(_Stage.FAILED)

        elif etype == RuntimeEventType.SESSION_IDLE:
            self._enter_idle()

        # All other events are explicitly ignored — no defaults.

        self._redraw()

    def _enter_stage(self, stage: _Stage) -> None:
        """Enter a new stage and reset the duration clock."""
        self._stage = stage
        self._stage_start = time.perf_counter()

    def _enter_idle(self) -> None:
        """Return to the idle state and clear all transient data."""
        self._stage = _Stage.IDLE
        self._active_name = ""
        self._stage_start = 0.0

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _refresh_duration(self) -> None:
        """Called by the UI timer to repaint only the elapsed duration.
        
        This method never mutates state. It only re-renders.
        """
        if self._stage not in (_Stage.IDLE, _Stage.APPROVAL, _Stage.FAILED):
            self._redraw()

    def _build_display_text(self) -> str:
        """Build the full display string from current state."""
        if self._stage == _Stage.IDLE:
            return "SAMAKTHA  |  Ready"

        if self._stage == _Stage.APPROVAL:
            return "SAMAKTHA  |  Waiting for approval"

        if self._stage == _Stage.FAILED:
            return "SAMAKTHA  |  Workflow failed"

        elapsed = self._elapsed()

        if self._stage == _Stage.CAP:
            return f"SAMAKTHA  |  CAP  |  {elapsed}"

        if self._stage == _Stage.GAMBIT:
            return f"SAMAKTHA  |  GAMBIT  |  {elapsed}"

        if self._stage == _Stage.WORKFLOW:
            return f"SAMAKTHA  |  WORKFLOW  |  {elapsed}"

        if self._stage == _Stage.TOOL:
            name = self._active_name or "unknown"
            return f"SAMAKTHA  |  WORKFLOW  |  Tool: {name}  |  {elapsed}"

        if self._stage == _Stage.PROVIDER:
            name = self._active_name or "unknown"
            return f"SAMAKTHA  |  WORKFLOW  |  Provider: {name}  |  {elapsed}"

        if self._stage == _Stage.MEMORY:
            return f"SAMAKTHA  |  MEMORY  |  {elapsed}"

        return "SAMAKTHA  |  Ready"

    def _elapsed(self) -> str:
        """Return a formatted elapsed duration string."""
        if self._stage_start == 0.0:
            return "0.00s"
        seconds = time.perf_counter() - self._stage_start
        return f"{seconds:.2f}s"

    def _redraw(self) -> None:
        """Compute the display text and update the label if it changed."""
        text = self._build_display_text()
        if text != self._display_text:
            self._display_text = text
            try:
                label = self.query_one("#status-bar-label", Label)
                label.update(text)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _detach_bus(self) -> None:
        if self._bus is not None and self._sub_id is not None:
            try:
                self._bus.unsubscribe(self._sub_id)
            except Exception:
                pass
        self._bus = None
        self._sub_id = None

    # ------------------------------------------------------------------
    # Properties for testing (read-only)
    # ------------------------------------------------------------------

    @property
    def stage(self) -> str:
        """Return the name of the current stage (for tests)."""
        return self._stage.name

    @property
    def active_name(self) -> str:
        """Return the currently active tool/provider name (for tests)."""
        return self._active_name

    @property
    def display_text(self) -> str:
        """Return the current display text (for tests)."""
        return self._build_display_text()
