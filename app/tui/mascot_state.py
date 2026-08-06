"""Phase 6.5 — Samaktha Mascot State Machine.

Maps AgentEvents to visual MascotStates. This is PURELY presentation logic.
No backend imports. No planning. No execution.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable, Optional

from app.agent.models import AgentEvent


class MascotState(str, Enum):
    """Visual states the mascot companion can be in."""
    IDLE             = "IDLE"
    LISTENING        = "LISTENING"
    THINKING         = "THINKING"
    SEARCHING_MEMORY = "SEARCHING_MEMORY"
    PLANNING         = "PLANNING"
    EXECUTING        = "EXECUTING"
    STREAMING        = "STREAMING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    SUCCESS          = "SUCCESS"
    ERROR            = "ERROR"
    SLEEPING         = "SLEEPING"


# ---------------------------------------------------------------------------
# Emoji and label representations (presentation-only)
# ---------------------------------------------------------------------------

MASCOT_STATE_VISUALS: dict[MascotState, tuple[str, str]] = {
    MascotState.IDLE:             ("🟠", "Idle"),
    MascotState.LISTENING:        ("🟡", "Listening…"),
    MascotState.THINKING:         ("🟠", "Thinking…"),
    MascotState.SEARCHING_MEMORY: ("🟠", "Searching Memory…"),
    MascotState.PLANNING:         ("🟡", "Planning…"),
    MascotState.EXECUTING:        ("🟠", "Executing Tools…"),
    MascotState.STREAMING:        ("🟠", "Streaming…"),
    MascotState.WAITING_APPROVAL: ("🟡", "Waiting for Approval…"),
    MascotState.SUCCESS:          ("🟢", "Success"),
    MascotState.ERROR:            ("🔴", "Error"),
    MascotState.SLEEPING:         ("⚫", "Sleeping"),
}


# Map of AgentEvent → resulting MascotState
_EVENT_TO_STATE: dict[AgentEvent, MascotState] = {
    AgentEvent.USER_MESSAGE:    MascotState.LISTENING,
    AgentEvent.PLAN_STARTED:    MascotState.PLANNING,
    AgentEvent.PLAN_FINISHED:   MascotState.SUCCESS,
    AgentEvent.TOOL_STARTED:    MascotState.EXECUTING,
    AgentEvent.TOOL_FINISHED:   MascotState.IDLE,
    AgentEvent.MODEL_SELECTED:  MascotState.THINKING,
    AgentEvent.STREAM_STARTED:  MascotState.STREAMING,
    AgentEvent.STREAM_FINISHED: MascotState.IDLE,
    AgentEvent.MEMORY_UPDATED:  MascotState.SEARCHING_MEMORY,
    AgentEvent.SESSION_CREATED: MascotState.IDLE,
    AgentEvent.ASSISTANT_MESSAGE: MascotState.IDLE,
    AgentEvent.PAUSE_REQUESTED: MascotState.WAITING_APPROVAL,
    AgentEvent.ERROR_OCCURRED:  MascotState.ERROR,
}


class MascotController:
    """Maps AgentEvents to MascotStates and notifies a registered callback."""

    def __init__(self, on_state_change: Optional[Callable[[MascotState], None]] = None):
        self._state = MascotState.IDLE
        self._on_state_change = on_state_change

    @property
    def state(self) -> MascotState:
        return self._state

    def handle_event(self, event: AgentEvent, data: dict) -> MascotState:
        """Transition to the appropriate state based on the agent event."""
        new_state = _EVENT_TO_STATE.get(event, MascotState.IDLE)
        if new_state != self._state:
            self._state = new_state
            if self._on_state_change:
                self._on_state_change(new_state)
        return self._state

    def set_sleeping(self) -> None:
        """Manually put the mascot to sleep (e.g. idle timeout)."""
        self._state = MascotState.SLEEPING
        if self._on_state_change:
            self._on_state_change(MascotState.SLEEPING)

    def get_visual(self) -> tuple[str, str]:
        """Return (emoji, label) for the current state."""
        return MASCOT_STATE_VISUALS.get(self._state, ("🟠", self._state.value))
