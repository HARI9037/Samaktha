"""Capability Registry — answers two questions only:
  1. Is this capability domain installed?
  2. Which tool provides it?

The planner consults this before building an ExecutionPlan.
If a capability is not installed, execution stops before Workflow starts.

Architecture rule: This registry is read-only. Planning logic MUST NOT live here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING

from app.tools.models import CapabilityAvailability

if TYPE_CHECKING:
    from app.tools.registry import ToolRegistry


@dataclass(frozen=True)
class CapabilityEntry:
    """Describes a single installed capability domain."""

    domain: str
    """Human-readable capability domain name (e.g. 'email', 'filesystem')."""

    tool_id: str | None
    """The tool_id that handles this domain in ToolRegistry."""

    description: str = ""
    """Optional short description for diagnostics."""

    supported_actions: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    availability: CapabilityAvailability = CapabilityAvailability.INTERNAL_ONLY
    side_effect_actions: tuple[str, ...] = ()
    evidence_requirements: dict[str, str] = field(default_factory=dict)
    natural_language_intents: tuple[str, ...] = ()
    advertised: bool = False


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

    def __init__(
        self,
        entries: List[CapabilityEntry] | None = None,
        *,
        source_registry: "ToolRegistry | None" = None,
    ) -> None:
        self._entries: Dict[str, CapabilityEntry] = {}
        self.source_registry = source_registry
        for entry in (entries or []):
            self._entries[entry.domain.lower()] = entry

    # ------------------------------------------------------------------
    # Public API — the only two questions the registry answers
    # ------------------------------------------------------------------

    def is_installed(self, domain: str) -> bool:
        """Return True if the given capability domain has a registered tool."""
        entry = self._entries.get(domain.lower())
        return bool(
            entry
            and entry.tool_id
            and entry.availability != CapabilityAvailability.UNAVAILABLE
        )

    def is_action_available(self, domain: str, action: str) -> bool:
        entry = self._entries.get(domain.lower())
        return bool(
            self.is_installed(domain)
            and entry
            and action in entry.supported_actions
        )

    def register(self, entry: CapabilityEntry) -> None:
        """Install a capability domain, rejecting duplicate domains.

        Added for P2.1 Plugin Architecture so that plugin-declared
        capability domains can be installed through the canonical registry.
        The registry stays read-only for planning logic; this is a
        registration API only.
        """
        domain = entry.domain.lower()
        if domain in self._entries:
            raise ValueError(f"Capability domain already installed: {entry.domain}")
        self._entries[domain] = entry

    def unregister_domain(self, domain: str) -> bool:
        """Remove a capability domain (idempotent)."""
        return self._entries.pop(domain.lower(), None) is not None


    def tool_for(self, domain: str) -> Optional[str]:
        """Return the tool_id for the given domain, or None if not installed."""
        entry = self._entries.get(domain.lower())
        return entry.tool_id if entry else None

    def entry_for(self, domain: str) -> CapabilityEntry | None:
        return self._entries.get(domain.lower())

    def advertised_entries(self) -> List[CapabilityEntry]:
        return sorted(
            (entry for entry in self._entries.values() if entry.advertised),
            key=lambda entry: entry.domain,
        )

    # ------------------------------------------------------------------
    # Introspection helpers (diagnostics only, not for planning logic)
    # ------------------------------------------------------------------

    def installed_domains(self) -> List[str]:
        """Return a sorted list of all installed capability domains."""
        return sorted(self._entries.keys())

    def entries(self) -> List[CapabilityEntry]:
        """Return all installed capability entries (introspection only)."""
        return list(self._entries.values())

    def uninstalled_domains(self) -> List[str]:
        """Return a sorted list of known-but-not-installed domains."""
        return sorted(
            d for d in _KNOWN_DOMAINS if d not in self._entries
        )

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_tool_registry(cls, tool_registry: "ToolRegistry") -> "CapabilityRegistry":
        """Derive product availability from the exact registered composition.

        Only ToolInfo records carrying an explicit product_domain participate.
        This prevents a class existing on disk, or a broad static declaration,
        from becoming an advertised production capability.
        """
        entries: list[CapabilityEntry] = []
        for info in tool_registry.list_tools():
            if not info.product_domain:
                continue
            actions = tuple(info.supported_actions or info.capabilities)
            availability = (
                info.execution_mode
                if info.available
                else CapabilityAvailability.UNAVAILABLE
            )
            entries.append(
                CapabilityEntry(
                    domain=info.product_domain,
                    tool_id=info.tool_id if info.available else None,
                    description=info.description,
                    supported_actions=actions,
                    permissions=tuple(info.permissions),
                    availability=availability,
                    side_effect_actions=tuple(info.side_effect_actions),
                    evidence_requirements=dict(info.evidence_requirements),
                    natural_language_intents=tuple(info.natural_language_intents),
                    advertised=bool(info.advertised and info.available),
                )
            )
        registered_domains = {entry.domain for entry in entries}
        for domain in sorted(_UNAVAILABLE_PRODUCT_CAPABILITIES - registered_domains):
            entries.append(
                CapabilityEntry(
                    domain=domain,
                    tool_id=None,
                    availability=CapabilityAvailability.UNAVAILABLE,
                    advertised=False,
                )
            )
        return cls(entries, source_registry=tool_registry)

    @staticmethod
    def default() -> "CapabilityRegistry":
        """Return no installed product capabilities.

        Production must use from_tool_registry().  This conservative fallback
        prevents standalone planners from advertising unwired tools.
        """
        return CapabilityRegistry(
            [
                CapabilityEntry(
                    domain=domain,
                    tool_id=None,
                    availability=CapabilityAvailability.UNAVAILABLE,
                )
                for domain in sorted(_KNOWN_DOMAINS)
            ]
        )


# Known domains that are NOT yet installed.
# These are used to generate user-facing "Capability not installed" messages.
_KNOWN_DOMAINS = {
    "filesystem", "pdf", "image", "memory", "windows", "terminal", "internet",
    "reminder", "note", "task", "contact", "calendar",
    "email", "message", "notification",
    # Not yet installed:
    "sms", "whatsapp", "telegram", "slack", "discord", "webhook", "push",
}

_UNAVAILABLE_PRODUCT_CAPABILITIES = {"browser", "media"}
