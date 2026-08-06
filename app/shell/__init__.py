"""Samaktha Shell Layer (Phase 11.1).

Deterministic slash-command handling for the Samaktha TUI. The Command Router
sits between the TUI and the orchestrator; slash commands never reach the
GoalParser / CAP / GAMBIT / LLM / Provider pipeline.
"""

from app.shell.command_router import (
    COMMAND_DEFINITIONS,
    CommandResult,
    CommandRouter,
    command_names,
    format_session_label,
    format_session_time,
)

__all__ = [
    "COMMAND_DEFINITIONS",
    "CommandResult",
    "CommandRouter",
    "command_names",
    "format_session_label",
    "format_session_time",
]
