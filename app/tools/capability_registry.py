"""Capability Registry — answers two questions only:
  1. Is this capability domain installed?
  2. Which tool provides it?

The planner consults this before building an ExecutionPlan.
If a capability is not installed, execution stops before Workflow starts.

Architecture rule: This registry is read-only. Planning logic MUST NOT live here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class CapabilityEntry:
    """Describes a single installed capability domain."""

    domain: str
    """Human-readable capability domain name (e.g. 'email', 'filesystem')."""

    tool_id: str
    """The tool_id that handles this domain in ToolRegistry."""

    description: str = ""
    """Optional short description for diagnostics."""


class CapabilityRegistry:
    """Maps capability domains to installed tools.

    A domain is NOT the same as a GoalIntent.
    Domains represent system-level capabilities (e.g. 'email', 'pdf', 'browser').
    GoalIntents describe what the user wants (e.g. READ_RESOURCE, LIST_DIRECTORY).

    Usage::

        registry = CapabilityRegistry.default()
        if registry.is_installed("email"):
            ...
        tool_id = registry.tool_for("pdf")  # → "pdf"
    """

    def __init__(self, entries: List[CapabilityEntry] | None = None) -> None:
        self._entries: Dict[str, CapabilityEntry] = {}
        for entry in (entries or []):
            self._entries[entry.domain.lower()] = entry

    # ------------------------------------------------------------------
    # Public API — the only two questions the registry answers
    # ------------------------------------------------------------------

    def is_installed(self, domain: str) -> bool:
        """Return True if the given capability domain has a registered tool."""
        return domain.lower() in self._entries

    def tool_for(self, domain: str) -> Optional[str]:
        """Return the tool_id for the given domain, or None if not installed."""
        entry = self._entries.get(domain.lower())
        return entry.tool_id if entry else None

    # ------------------------------------------------------------------
    # Introspection helpers (diagnostics only, not for planning logic)
    # ------------------------------------------------------------------

    def installed_domains(self) -> List[str]:
        """Return a sorted list of all installed capability domains."""
        return sorted(self._entries.keys())

    def uninstalled_domains(self) -> List[str]:
        """Return a sorted list of known-but-not-installed domains."""
        return sorted(
            d for d in _KNOWN_DOMAINS if d not in self._entries
        )

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @staticmethod
    def default() -> "CapabilityRegistry":
        """Return a registry pre-populated with Samaktha's installed tools.

        Add entries here as new tools are implemented.
        Known-but-uninstalled domains are declared in _KNOWN_DOMAINS below
        so that the planner can produce a helpful error message.
        """
        return CapabilityRegistry(
            entries=[
                CapabilityEntry(
                    domain="filesystem",
                    tool_id="resolver",
                    description="Local filesystem: read, write, list, move, copy, delete",
                ),
                CapabilityEntry(
                    domain="pdf",
                    tool_id="pdf",
                    description="PDF text extraction and metadata",
                ),
                CapabilityEntry(
                    domain="image",
                    tool_id="image",
                    description="Image analysis and metadata",
                ),
                CapabilityEntry(
                    domain="memory",
                    tool_id="memory",
                    description="Conversation and skill memory search",
                ),
                CapabilityEntry(
                    domain="windows",
                    tool_id="windows",
                    description="Windows OS: processes, clipboard, terminal",
                ),
                CapabilityEntry(
                    domain="terminal",
                    tool_id="windows",
                    description="Execute terminal/shell commands (via Windows tool)",
                ),
                CapabilityEntry(
                    domain="document",
                    tool_id="document",
                    description="Document reading, summarization, table extraction, and metadata",
                ),
            ]
        )


# Known domains that are NOT yet installed.
# These are used to generate user-facing "Capability not installed" messages.
_KNOWN_DOMAINS = {
    "filesystem", "pdf", "image", "memory", "windows", "terminal",
    # Not yet installed:
    "email", "calendar", "browser", "git", "spotify", "slack",
    "notion", "drive", "dropbox", "jira", "github",
}
