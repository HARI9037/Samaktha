"""P2.3 — Versioned Capability Contracts: comparison and breaking-change detection.

Compatibility is decided structurally: a new contract is compatible when it
preserves every capability, action, permission, parameter and output key the
old contract promised (a strict superset). The version number is never
trusted on its own — a bumped major version without surface changes is fine,
and a patch bump that drops a capability is still a breaking change.
"""

from __future__ import annotations

from app.capabilities.models import (
    CapabilityContract,
    ContractChange,
    ContractChangeKind,
    ContractComparison,
)


class ContractError(ValueError):
    """Raised when contracts cannot be compared or registered."""


def _surface_deltas(
    old_set: frozenset[str],
    new_set: frozenset[str],
    category: ContractChangeKind,
    label: str,
    breaking_removal: bool = True,
) -> list[ContractChange]:
    changes: list[ContractChange] = []
    for removed in sorted(old_set - new_set):
        changes.append(
            ContractChange(
                category=category,
                breaking=breaking_removal,
                detail=f"{label} removed: {removed}",
            )
        )
    for added in sorted(new_set - old_set):
        changes.append(
            ContractChange(
                category=category,
                breaking=False,
                detail=f"{label} added: {added}",
            )
        )
    return changes


def compare_contracts(
    old: CapabilityContract,
    new: CapabilityContract,
) -> ContractComparison:
    """Compare ``old`` against ``new`` for the same capability surface.

    Raises ``ContractError`` when the two contracts describe different
    contributions.
    """
    if old.key != new.key:
        raise ContractError(
            f"Cannot compare unrelated contracts: {old.key!r} vs {new.key!r}"
        )

    changes: list[ContractChange] = []
    changes.extend(
        _surface_deltas(
            frozenset(old.capabilities),
            frozenset(new.capabilities),
            ContractChangeKind.CAPABILITY,
            "Capability",
        )
    )
    changes.extend(
        _surface_deltas(
            frozenset(old.actions),
            frozenset(new.actions),
            ContractChangeKind.ACTION,
            "Action",
        )
    )
    changes.extend(
        _surface_deltas(
            frozenset(old.permissions),
            frozenset(new.permissions),
            ContractChangeKind.PERMISSION,
            "Permission",
        )
    )
    changes.extend(
        _surface_deltas(
            frozenset(old.output_keys),
            frozenset(new.output_keys),
            ContractChangeKind.OUTPUT,
            "Output key",
        )
    )
    changes.extend(
        _surface_deltas(
            old.parameter_names,
            new.parameter_names,
            ContractChangeKind.PARAMETER,
            "Parameter",
        )
    )

    for added in sorted(new.required_parameter_names - old.required_parameter_names):
        if added not in old.parameter_names:
            changes.append(
                ContractChange(
                    category=ContractChangeKind.PARAMETER,
                    breaking=True,
                    detail=f"Required parameter added: {added}",
                )
            )

    old_v = old.semver
    new_v = new.semver
    if old_v == new_v:
        if changes:
            changes.append(
                ContractChange(
                    category=ContractChangeKind.VERSION,
                    breaking=True,
                    detail=(
                        f"Version unchanged ({old.version}) but capability "
                        "surface differs"
                    ),
                )
            )
    elif new_v < old_v:
        changes.append(
            ContractChange(
                category=ContractChangeKind.VERSION,
                breaking=True,
                detail=(
                    f"Downgrade: new version {new.version} is older than "
                    f"{old.version}"
                ),
            )
        )
    elif new_v.major > old_v.major:
        changes.append(
            ContractChange(
                category=ContractChangeKind.VERSION,
                breaking=False,
                detail=(
                    f"Major version change: {old.version} -> {new.version}"
                ),
            )
        )

    return ContractComparison(
        old=old,
        new=new,
        compatible=not any(c.breaking for c in changes),
        changes=changes,
    )


def is_compatible(old: CapabilityContract, new: CapabilityContract) -> bool:
    """True when ``new`` preserves the full surface of ``old``."""
    return compare_contracts(old, new).compatible


def breaking_changes(
    old: CapabilityContract, new: CapabilityContract
) -> list[ContractChange]:
    """The breaking differences between ``old`` and ``new``."""
    return compare_contracts(old, new).breaking_changes


def is_semver_compatible(
    old: CapabilityContract, new: CapabilityContract
) -> bool:
    """True when ``new`` is a same-major (or newer) version of ``old``."""
    return new.semver.major == old.semver.major and new.semver >= old.semver
