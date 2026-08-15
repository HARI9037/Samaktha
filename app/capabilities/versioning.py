"""P2.3 — Versioned Capability Contracts: versioning strategy.

Semver discipline over contracts: any breaking surface change demands a major
bump, any additive change at least a minor bump, and fixes without surface
changes only a patch. ``recommended_bump`` derives the required bump from the
structural comparison, and ``version_respects_bump`` verifies that an author
actually followed it.
"""

from __future__ import annotations

from app.capabilities.compat import compare_contracts
from app.capabilities.models import CapabilityContract, ContractChangeKind


def recommended_bump(
    old: CapabilityContract, new: CapabilityContract
) -> str:
    """The bump ``new`` requires relative to ``old``.

    Returns ``"none"``, ``"patch"``, ``"minor"`` or ``"major"``. Only surface
    changes (capabilities, actions, permissions, parameters, output keys)
    drive the recommendation; informational version-change notes do not.
    """
    comparison = compare_contracts(old, new)
    if comparison.breaking_changes:
        return "major"
    surface_changes = [
        c for c in comparison.changes
        if c.category != ContractChangeKind.VERSION
    ]
    if surface_changes:
        return "minor"
    if new.semver != old.semver:
        return "patch"
    return "none"


def version_respects_bump(
    old: CapabilityContract, new: CapabilityContract
) -> tuple[bool, str]:
    """Check that ``new.version`` honours the required bump discipline.

    Returns ``(ok, reason)``.
    """
    bump = recommended_bump(old, new)
    if bump == "none":
        return True, "no surface change and no version change"
    if bump == "major":
        ok = new.semver.major > old.semver.major
    elif bump == "minor":
        ok = new.semver.minor > old.semver.minor
    else:
        ok = (
            new.semver.patch > old.semver.patch
            or new.semver.minor > old.semver.minor
            or new.semver.major > old.semver.major
        )
    if ok:
        return True, f"{bump} bump satisfied ({old.version} -> {new.version})"
    return (
        False,
        f"surface change requires a {bump} bump, but got "
        f"{old.version} -> {new.version}",
    )


def compatible_range(version: str) -> str:
    """Constraint matching same-major compatible upgrades (``^1.2.3``)."""
    return f"^{version}"
