"""Tool error hierarchy.

All errors raised by tools during execution inherit from ToolError so
that callers can distinguish tool failures from framework failures and
decide retry/rollback behaviour without inspecting string messages.
"""

from __future__ import annotations


class ToolError(Exception):
    """Base class for every error raised in the tool ecosystem."""


class ToolNotFoundError(ToolError):
    """Requested tool id is not registered."""


class ToolUnavailableError(ToolError):
    """Tool is registered but currently unavailable or disabled."""


class ToolValidationError(ToolError):
    """Input arguments failed validation."""


class ToolPermissionError(ToolError):
    """The executing context lacks a required permission."""


class ToolTimeoutError(ToolError):
    """Tool execution exceeded its allowed time budget."""


class ToolExecutionError(ToolError):
    """The tool ran but failed while performing its work."""


class ToolCancelledError(ToolError):
    """Tool execution was cancelled before completion."""


class ToolDependencyError(ToolError):
    """A registered tool depends on another tool that is unavailable."""
