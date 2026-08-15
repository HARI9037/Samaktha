"""Minimal semantic version parsing and constraint evaluation (P2.1).

Used by the Plugin specification for ``manifest.version`` and dependency
constraints. Only strict ``MAJOR.MINOR.PATCH`` versions are accepted, with
optional ``-prerelease`` / ``+build`` suffixes tolerated (ignored during
comparison). This keeps the Plugin Architecture free of a heavyweight
versioning dependency while remaining deterministic.
"""

from __future__ import annotations

import re
from functools import total_ordering

_PATTERN = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)(?:[-+][0-9A-Za-z.-]+)?$"
)


class VersionError(ValueError):
    """Raised when a version string is not valid semantic versioning."""


@total_ordering
class SemanticVersion:
    """An immutable, ordered ``MAJOR.MINOR.PATCH`` version."""

    __slots__ = ("major", "minor", "patch")

    def __init__(self, major: int, minor: int, patch: int) -> None:
        if major < 0 or minor < 0 or patch < 0:
            raise VersionError("Version components must be non-negative.")
        self.major = major
        self.minor = minor
        self.patch = patch

    @classmethod
    def parse(cls, value: str) -> "SemanticVersion":
        """Parse a strict semver string."""
        if not isinstance(value, str):
            raise VersionError(f"Version must be a string, got {type(value).__name__}.")
        match = _PATTERN.match(value.strip())
        if not match:
            raise VersionError(f"Invalid semantic version: {value!r}.")
        return cls(int(match["major"]), int(match["minor"]), int(match["patch"]))

    def satisfies(self, constraint: str) -> bool:
        """True when this version satisfies ``constraint``."""
        return satisfies(self, constraint)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def __repr__(self) -> str:
        return f"SemanticVersion({self.major}, {self.minor}, {self.patch})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SemanticVersion):
            return NotImplemented
        return (self.major, self.minor, self.patch) == (other.major, other.minor, other.patch)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemanticVersion):
            return NotImplemented
        return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)


def satisfies(version: SemanticVersion, constraint: str) -> bool:
    """Evaluate a semver constraint against ``version``.

    Supported operators:
      * ``*`` or ``""``      any version
      * ``1.2.3``            exact
      * ``>=1.2``, ``>``, ``<=``, ``<``, ``==``
      * ``^1.2.3``           same major, at least the given minor/patch
      * ``~1.2.3``           same major+minor, at least the given patch
    """
    if constraint is None:
        return False
    constraint = str(constraint).strip()
    if constraint in ("", "*"):
        return True
    if constraint.startswith(">="):
        return version >= SemanticVersion.parse(constraint[2:].strip())
    if constraint.startswith("<="):
        return version <= SemanticVersion.parse(constraint[2:].strip())
    if constraint.startswith(">"):
        return version > SemanticVersion.parse(constraint[1:].strip())
    if constraint.startswith("<"):
        return version < SemanticVersion.parse(constraint[1:].strip())
    if constraint.startswith("=="):
        return version == SemanticVersion.parse(constraint[2:].strip())
    if constraint.startswith("^"):
        base = SemanticVersion.parse(constraint[1:].strip())
        return (version.major, version.minor, version.patch) >= (base.major, base.minor, base.patch) and version.major == base.major
    if constraint.startswith("~"):
        base = SemanticVersion.parse(constraint[1:].strip())
        return (version.major, version.minor) == (base.major, base.minor) and version.patch >= base.patch
    return version == SemanticVersion.parse(constraint)


def validate_constraint(constraint: str) -> None:
    """Validate a dependency constraint string; raises ``VersionError``."""
    if not isinstance(constraint, str):
        raise VersionError("Constraint must be a string.")
    constraint = constraint.strip()
    if constraint in ("", "*"):
        return
    for prefix in (">=", "<=", ">", "<", "==", "^", "~"):
        if constraint.startswith(prefix):
            SemanticVersion.parse(constraint[len(prefix):].strip())
            return
    SemanticVersion.parse(constraint)
