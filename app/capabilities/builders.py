"""P2.3 — Versioned Capability Contracts: builders.

Derive ``CapabilityContract`` objects from canonical runtime artifacts:
``ToolInfo`` for tools, ``CommunicationProvider`` for providers, and explicit
declarations for skills and personalities. Every builder returns a
deterministic contract with strict semantic versioning.
"""

from __future__ import annotations

from typing import Any, Iterable

from app.capabilities.models import CapabilityContract, ContractParameter
from app.plugins.models import PluginKind


def _as_str(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _schema_parameters(input_schema: dict[str, Any]) -> list[ContractParameter]:
    properties = dict((input_schema or {}).get("properties", {}) or {})
    required = set((input_schema or {}).get("required", []) or [])
    return [
        ContractParameter(name=str(name), required=name in required)
        for name in properties
    ]


def contract_for_tool(
    info: Any,
    *,
    version: str | None = None,
) -> CapabilityContract:
    """Build a tool contract from a registered tool's ``ToolInfo``."""
    capabilities = [_as_str(c) for c in getattr(info, "capabilities", None) or ()]
    actions = [_as_str(a) for a in getattr(info, "supported_actions", None) or ()]
    permissions = [_as_str(p) for p in getattr(info, "permissions", None) or ()]
    schema = dict(getattr(info, "input_schema", None) or {})
    metadata = dict(getattr(info, "metadata", None) or {})
    return CapabilityContract(
        kind=PluginKind.TOOL,
        name=str(info.tool_id),
        version=version or getattr(info, "version", None) or "1.0.0",
        description=str(getattr(info, "description", None) or ""),
        capabilities=sorted(set(capabilities)),
        actions=sorted(set(actions)),
        permissions=sorted(set(permissions)),
        parameters=_schema_parameters(schema),
        metadata={"source": metadata.get("source", "system")},
    )


def contract_for_provider(
    provider_id: str,
    *,
    version: str = "1.0.0",
    description: str = "",
    capabilities: Iterable[str] = (),
    actions: Iterable[str] = (),
    permissions: Iterable[str] = (),
) -> CapabilityContract:
    """Build a provider contract from explicit declarations."""
    return CapabilityContract(
        kind=PluginKind.PROVIDER,
        name=str(provider_id),
        version=version,
        description=description,
        capabilities=sorted(set(_as_str(c) for c in capabilities)),
        actions=sorted(set(_as_str(a) for a in actions)),
        permissions=sorted(set(_as_str(p) for p in permissions)),
        metadata={"source": "provider"},
    )


def contract_for_skill(
    skill_id: str,
    *,
    version: str = "1.0.0",
    description: str = "",
    capabilities: Iterable[str] = (),
    parameters: Iterable[ContractParameter] = (),
    output_keys: Iterable[str] = (),
) -> CapabilityContract:
    """Build a skill contract from explicit declarations."""
    return CapabilityContract(
        kind=PluginKind.SKILL,
        name=str(skill_id),
        version=version,
        description=description,
        capabilities=sorted(set(_as_str(c) for c in capabilities)),
        parameters=list(parameters),
        output_keys=sorted(set(output_keys)),
        metadata={"source": "skill"},
    )


def contract_for_personality(
    personality_id: str,
    *,
    version: str = "1.0.0",
    description: str = "",
    capabilities: Iterable[str] = (),
    parameters: Iterable[ContractParameter] = (),
) -> CapabilityContract:
    """Build a personality contract from explicit declarations."""
    return CapabilityContract(
        kind=PluginKind.PERSONALITY,
        name=str(personality_id),
        version=version,
        description=description,
        capabilities=sorted(set(_as_str(c) for c in capabilities)),
        parameters=list(parameters),
        metadata={"source": "personality"},
    )
