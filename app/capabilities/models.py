"""P2.3 — Versioned Capability Contracts: models.

A capability contract is the machine-readable, versioned declaration of the
capability surface a contribution offers — a tool, provider, skill or
personality. Contracts exist independently of plugin manifests so that
system tools and plugin contributions are compared, versioned and migrated
through a single mechanism.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.plugins.models import PluginKind
from app.plugins.semver import SemanticVersion


class ContractChangeKind(StrEnum):
    """Category of a difference between two contract versions."""

    CAPABILITY = "capability"
    ACTION = "action"
    PERMISSION = "permission"
    PARAMETER = "parameter"
    OUTPUT = "output"
    VERSION = "version"


class ContractParameter(BaseModel):
    """A single input parameter of a contract's surface."""

    name: str
    required: bool = True
    description: str = ""


class CapabilityContract(BaseModel):
    """A versioned, machine-readable capability surface.

    ``kind`` and ``name`` together identify the contribution; ``version`` is
    strict semantic versioning. Compatibility is decided by comparing the
    surface (capabilities, actions, permissions, parameters, output keys)
    between versions — never by trusting the version number alone.
    """

    kind: PluginKind
    name: str
    version: str = "1.0.0"
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    parameters: list[ContractParameter] = Field(default_factory=list)
    output_keys: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def key(self) -> str:
        """Canonical contract key: ``kind:name``."""
        return f"{self.kind.value}:{self.name}"

    @property
    def semver(self) -> SemanticVersion:
        """The contract version parsed as strict semver."""
        return SemanticVersion.parse(self.version)

    @property
    def parameter_names(self) -> frozenset[str]:
        return frozenset(p.name for p in self.parameters)

    @property
    def required_parameter_names(self) -> frozenset[str]:
        return frozenset(p.name for p in self.parameters if p.required)


class ContractChange(BaseModel):
    """A single difference detected between two contract versions."""

    category: ContractChangeKind
    breaking: bool
    detail: str


class ContractComparison(BaseModel):
    """Result of comparing an older contract against a newer one.

    ``compatible`` is True when the new surface preserves everything the old
    surface promised (no breaking changes). Breaking changes are the subset
    of ``changes`` flagged with ``breaking=True``.
    """

    old: CapabilityContract
    new: CapabilityContract
    compatible: bool
    changes: list[ContractChange] = Field(default_factory=list)

    @property
    def breaking_changes(self) -> list[ContractChange]:
        return [c for c in self.changes if c.breaking]

    @property
    def additive_changes(self) -> list[ContractChange]:
        return [c for c in self.changes if not c.breaking]
