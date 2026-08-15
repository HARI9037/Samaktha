"""P2.3 — Versioned Capability Contracts: migration strategy.

Given an installed contract and a proposed upgrade, ``plan_migration``
produces a deterministic migration plan: is the upgrade compatible, does it
require a consumer update, and what exactly changed. ``upgrade_path`` answers
the same question against a contract registry, and ``is_consumer_compatible``
checks a consumer's version constraint against a contract.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.capabilities.compat import compare_contracts
from app.capabilities.models import (
    CapabilityContract,
    ContractChange,
    ContractComparison,
)
from app.capabilities.registry import ContractRegistry
from app.plugins.models import PluginKind


class MigrationPlan(BaseModel):
    """A deterministic plan for upgrading from one contract version to another."""

    kind: PluginKind
    name: str
    from_version: str
    to_version: str
    compatible: bool
    requires_consumer_update: bool
    changes: list[ContractChange] = Field(default_factory=list)


def plan_migration(
    old: CapabilityContract, new: CapabilityContract
) -> MigrationPlan:
    """Plan the migration from ``old`` to ``new``."""
    comparison: ContractComparison = compare_contracts(old, new)
    return MigrationPlan(
        kind=old.kind,
        name=old.name,
        from_version=old.version,
        to_version=new.version,
        compatible=comparison.compatible,
        requires_consumer_update=bool(comparison.breaking_changes),
        changes=comparison.changes,
    )


def upgrade_path(
    registry: ContractRegistry,
    kind: PluginKind | str,
    name: str,
    to_version: Optional[str] = None,
    from_version: Optional[str] = None,
) -> Optional[MigrationPlan]:
    """Plan the upgrade from ``from_version`` (default: latest registered)
    to ``to_version`` (default: latest registered).

    Returns None when the registry holds no history for ``kind:name``, the
    from/to versions are not registered, or they are the same version.
    """
    old = registry.get(kind, name, from_version) if from_version else registry.latest(kind, name)
    if old is None:
        return None
    target = registry.get(kind, name, to_version) if to_version else registry.latest(kind, name)
    if target is None or target.semver == old.semver:
        return None
    return plan_migration(old, target)


def is_consumer_compatible(
    constraint: str, contract: CapabilityContract
) -> bool:
    """True when ``contract`` satisfies a consumer's version ``constraint``."""
    return contract.semver.satisfies(constraint)
