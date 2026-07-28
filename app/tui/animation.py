"""Phase 6.5 — Samaktha Animation Framework (State Machine Only).

Defines the reusable animation state machine for the mascot.
NO actual animations are rendered here — this is a framework for future phases.

Animation states supported:
- IDLE_BLINK
- IDLE_BREATHE
- THINKING_PULSE
- SUCCESS_FLASH
- ERROR_SHAKE
- SLEEPING_ZZZ
"""

from __future__ import annotations

from enum import Enum
from typing import Callable, Optional


class AnimationState(str, Enum):
    """States that a future animation renderer can react to."""
    IDLE_BLINK    = "IDLE_BLINK"
    IDLE_BREATHE  = "IDLE_BREATHE"
    THINKING_PULSE = "THINKING_PULSE"
    SUCCESS_FLASH = "SUCCESS_FLASH"
    ERROR_SHAKE   = "ERROR_SHAKE"
    SLEEPING_ZZZ  = "SLEEPING_ZZZ"
    NONE          = "NONE"


# Maps from MascotState name strings to AnimationState
# (decoupled so mascot_state.py doesn't need to import this module)
_MASCOT_TO_ANIMATION: dict[str, AnimationState] = {
    "IDLE":             AnimationState.IDLE_BREATHE,
    "LISTENING":        AnimationState.IDLE_BLINK,
    "THINKING":         AnimationState.THINKING_PULSE,
    "SEARCHING_MEMORY": AnimationState.THINKING_PULSE,
    "PLANNING":         AnimationState.THINKING_PULSE,
    "EXECUTING":        AnimationState.THINKING_PULSE,
    "STREAMING":        AnimationState.IDLE_BLINK,
    "WAITING_APPROVAL": AnimationState.IDLE_BLINK,
    "SUCCESS":          AnimationState.SUCCESS_FLASH,
    "ERROR":            AnimationState.ERROR_SHAKE,
    "SLEEPING":         AnimationState.SLEEPING_ZZZ,
}


class AnimationController:
    """
    Future-proof animation state machine.

    In Phase 6.5 this ONLY tracks the desired animation state.
    Future phases will attach actual Textual animation renderers.
    """

    def __init__(self, on_animation_change: Optional[Callable[[AnimationState], None]] = None):
        self._current = AnimationState.NONE
        self._on_change = on_animation_change

    @property
    def current(self) -> AnimationState:
        return self._current

    def from_mascot_state(self, mascot_state_name: str) -> AnimationState:
        """Update animation state derived from MascotState name."""
        desired = _MASCOT_TO_ANIMATION.get(mascot_state_name, AnimationState.NONE)
        if desired != self._current:
            self._current = desired
            if self._on_change:
                self._on_change(desired)
        return self._current
