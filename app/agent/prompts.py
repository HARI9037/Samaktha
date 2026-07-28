"""Centralized Provider prompt templates for Samaktha.

All prompts sent to ProviderExecutor must be defined here.
No hardcoded prompt strings are allowed inside agent/runtime.py or any
other runtime layer.

Architecture rule: Only this module may define the text of prompts.
Runtime code must import from here.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Tool summarization prompts
# ---------------------------------------------------------------------------

TOOL_SUMMARIZE_PROMPT: str = (
    "Tool execution completed. "
    "Please summarize the tool outputs and answer my original request "
    "based ONLY on the provided tool context. "
    "Do not speculate about information that was not returned by the tool."
)
"""Sent when a tool has executed and the Provider needs to summarize its output.

The tool output is already appended to the conversation history before this
prompt is evaluated. The Provider MUST NOT claim it cannot access files — the
tool has already retrieved the data.
"""

CAPABILITY_UNAVAILABLE_MESSAGE: str = (
    "Capability not installed.\nRequired capability: {capability}"
)
"""User-facing message template when a required capability is not installed.

Usage::
    msg = CAPABILITY_UNAVAILABLE_MESSAGE.format(capability="Email")
"""

CAP_DENY_MESSAGE: str = (
    "Request cancelled.\nPermission denied by user."
)
"""User-facing message when the user clicks Deny in a CAP approval widget."""

CAP_POLICY_BLOCK_MESSAGE: str = (
    "Request blocked by governance policy."
)
"""User-facing message when CAP's PolicyEngine blocks a request automatically."""
