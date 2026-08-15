"""P2.5 — Governance Maturity: policy-as-code foundation.

Loads, validates and registers versioned ``GovernancePolicy`` documents from
dicts/JSON files, mirroring the plugin manifest pattern (``id@version`` keys,
semver version strings, duplicate rejection). ``PolicyRegistry`` is the
canonical store; the governance engine resolves rules from the active
policies deterministically.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app.governance.models import GovernancePolicy
from app.plugins.semver import SemanticVersion, VersionError


class PolicyValidationError(RuntimeError):
    """Raised when a governance policy is malformed."""


class PolicyRegistrationError(RuntimeError):
    """Raised when a policy key is duplicated."""


def validate_policy(policy: Any) -> list[str]:
    """Return a list of problems with ``policy`` (empty when valid).

    Accepts a ``GovernancePolicy`` or a raw dict. Malformed input that cannot
    even be parsed into the model is reported as a problem (never raised
    here); callers such as :func:`load_policy` and ``PolicyRegistry.register``
    raise :class:`PolicyValidationError` when problems exist.
    """
    if not isinstance(policy, GovernancePolicy):
        try:
            policy = GovernancePolicy.model_validate(policy)
        except Exception as exc:  # pydantic ValidationError et al.
            return [f"Invalid governance policy: {exc}"]

    errors: list[str] = []

    if not policy.policy_id or not policy.policy_id.strip():
        errors.append("policy_id must not be empty.")
    if not policy.name.strip():
        errors.append("name must not be empty.")
    try:
        SemanticVersion.parse(policy.version)
    except VersionError as exc:
        errors.append(f"Invalid policy version: {exc}")

    seen_tools: set[str] = set()
    for rule in policy.tools:
        if rule.target in seen_tools:
            errors.append(f"Duplicate tool permission rule for {rule.target!r}.")
        seen_tools.add(rule.target)

    seen_providers: set[str] = set()
    for rule in policy.providers:
        if rule.target in seen_providers:
            errors.append(f"Duplicate provider permission rule for {rule.target!r}.")
        seen_providers.add(rule.target)

    seen_capabilities: set[str] = set()
    for rule in policy.capabilities:
        if rule.target in seen_capabilities:
            errors.append(f"Duplicate capability permission rule for {rule.target!r}.")
        seen_capabilities.add(rule.target)

    return errors


def load_policy(data: dict[str, Any]) -> GovernancePolicy:
    """Build a ``GovernancePolicy`` from a dict, validating it."""
    policy = GovernancePolicy.model_validate(data)
    errors = validate_policy(policy)
    if errors:
        raise PolicyValidationError("; ".join(errors))
    return policy


def load_policy_file(path: str | Path) -> GovernancePolicy:
    """Load and validate a governance policy from a JSON file."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return load_policy(payload)


class PolicyRegistry:
    """Canonical, versioned store of governance policies (``id@version``)."""

    def __init__(self) -> None:
        self._policies: dict[str, GovernancePolicy] = {}

    def register(self, policy: GovernancePolicy) -> GovernancePolicy:
        """Register a policy, rejecting duplicate ``id@version`` keys."""
        if policy.key in self._policies:
            raise PolicyRegistrationError(f"Policy already registered: {policy.key}")
        errors = validate_policy(policy)
        if errors:
            raise PolicyValidationError("; ".join(errors))
        self._policies[policy.key] = policy
        return policy

    def get(self, policy_key: str) -> Optional[GovernancePolicy]:
        return self._policies.get(policy_key)

    def has(self, policy_key: str) -> bool:
        if policy_key in self._policies:
            return True
        return "@" not in policy_key and self.latest(policy_key) is not None

    def latest(self, policy_id: str) -> Optional[GovernancePolicy]:
        """Highest-version registered policy for ``policy_id``."""
        matches = [p for p in self._policies.values() if p.policy_id == policy_id]
        if not matches:
            return None
        return max(matches, key=lambda p: (_version_tuple(p), p.key))

    def list(self) -> list[GovernancePolicy]:
        return [self._policies[key] for key in sorted(self._policies)]

    def count(self) -> int:
        return len(self._policies)

    def clear(self) -> None:
        self._policies.clear()


def _version_tuple(policy: GovernancePolicy) -> tuple[int, int, int]:
    version = SemanticVersion.parse(policy.version)
    return (version.major, version.minor, version.patch)
