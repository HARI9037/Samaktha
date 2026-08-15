"""Plugin isolation boundaries (P2.1 Plugin Architecture).

Enforces the separation between plugin contributions and the governed
runtime. Plugins may only:

  * contribute ``Tool`` instances (registered through the canonical
    ``ToolRegistry``);
  * contribute ``CommunicationProvider`` instances;
  * declare capability domains that are actually provided by their tools.

Plugins can never declare a permission they do not require, declare a
capability they do not provide, or bypass CAP by contributing arbitrary
callables. Execution of a plugin tool follows the exact same CAP/security
pipeline as any system tool because it is registered in the same registry.
"""

from __future__ import annotations

from typing import Iterable


class PluginIsolationError(RuntimeError):
    """Raised when a plugin contribution crosses an isolation boundary."""


def _stringify(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def enforce_tool_boundary(contribution) -> "object":
    """Require a ``Tool`` instance before registration."""
    from app.tools.base import Tool

    if not isinstance(contribution, Tool):
        raise PluginIsolationError(
            "Tool contributions must be instances of app.tools.base.Tool; "
            f"got {type(contribution).__name__}. Arbitrary callables are not "
            "registered as tools."
        )
    return contribution


def enforce_provider_boundary(contribution) -> "object":
    """Require a ``CommunicationProvider`` instance before registration."""
    from app.communication.provider import CommunicationProvider

    if not isinstance(contribution, CommunicationProvider):
        raise PluginIsolationError(
            "Provider contributions must be instances of "
            "app.communication.provider.CommunicationProvider; got "
            f"{type(contribution).__name__}."
        )
    return contribution


def enforce_permission_boundary(
    declared_scopes: Iterable[str], tools: Iterable[object]
) -> None:
    """Refuse tools that require permissions the manifest never declared.

    This is the core permission-declaration invariant: a plugin cannot
    silently demand more than it declares. Runtime grants remain CAP's
    decision — this only rejects undeclared requirements at load time.
    """
    declared = set(declared_scopes)
    for tool in tools:
        policy = getattr(tool, "policy", None)
        required = {_stringify(p) for p in (getattr(policy, "permissions", None) or ())}
        missing = required - declared
        if missing:
            raise PluginIsolationError(
                f"Tool '{tool.name}' requires undeclared permission(s): "
                f"{sorted(missing)}."
            )


def enforce_capability_boundary(
    declared_capabilities: Iterable[str], tools: Iterable[object]
) -> None:
    """Refuse tools that provide capabilities the manifest never declared."""
    declared = set(declared_capabilities)
    for tool in tools:
        provided = {
            _stringify(c) for c in (getattr(tool, "capabilities", None) or ())
        }
        missing = provided - declared
        if missing:
            raise PluginIsolationError(
                f"Tool '{tool.name}' provides undeclared capability/"
                f"capabilities: {sorted(missing)}."
            )
