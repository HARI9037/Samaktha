"""Phase 6.5 — Samaktha Personality Profiles.

Presentation-only UI text profiles for how Samaktha responds in the TUI.
Contains NO planning, NO execution, NO reasoning.
Only display strings and greeting/completion wording.
"""

from __future__ import annotations

from enum import Enum
from typing import NamedTuple


class PersonalityProfile(NamedTuple):
    """A bundle of UI text strings that define an agent persona."""
    name: str
    greeting: str
    thinking_label: str
    completion_label: str
    approval_prompt: str
    error_label: str
    idle_label: str


# ---------------------------------------------------------------------------
# Built-in profiles (pure text, no logic)
# ---------------------------------------------------------------------------

PROFILE_CORE = PersonalityProfile(
    name="Samaktha Core",
    greeting="Samaktha ready. How can I assist you today?",
    thinking_label="Analyzing your request…",
    completion_label="Task completed.",
    approval_prompt="This action requires your approval before continuing.",
    error_label="An error occurred. Please check the timeline for details.",
    idle_label="Waiting for input…",
)

PROFILE_ASSISTANT = PersonalityProfile(
    name="Helpful Assistant",
    greeting="Hello! I'm ready to help. What would you like to do?",
    thinking_label="Let me think about that…",
    completion_label="Done! Is there anything else?",
    approval_prompt="I need your confirmation before proceeding.",
    error_label="Something went wrong. Let me know if you'd like to try again.",
    idle_label="Ready and waiting…",
)

PROFILE_EXPERT = PersonalityProfile(
    name="Expert Mode",
    greeting="Expert agent online. Provide your objective.",
    thinking_label="Reasoning…",
    completion_label="Execution complete.",
    approval_prompt="Approval required for the next step.",
    error_label="Execution failed. Review error details.",
    idle_label="Standby.",
)


# All available profiles
ALL_PROFILES: dict[str, PersonalityProfile] = {
    "core":      PROFILE_CORE,
    "assistant": PROFILE_ASSISTANT,
    "expert":    PROFILE_EXPERT,
}

_DEFAULT_PROFILE_KEY = "core"


class PersonalityProfileManager:
    """Selects and retrieves the active personality profile for the TUI."""

    def __init__(self, profile_key: str = _DEFAULT_PROFILE_KEY):
        self._active_key = profile_key if profile_key in ALL_PROFILES else _DEFAULT_PROFILE_KEY

    @property
    def active(self) -> PersonalityProfile:
        return ALL_PROFILES[self._active_key]

    def set_profile(self, key: str) -> bool:
        """Switch to a different profile. Returns True on success."""
        if key in ALL_PROFILES:
            self._active_key = key
            return True
        return False

    def list_profiles(self) -> list[str]:
        return list(ALL_PROFILES.keys())
