"""P2.5 — Governance Maturity: policy violation handling.

A ``PolicyViolation`` is a deterministic, structured description of a
governance failure (denied permission, required approval, undeclared
requirement). The ``ViolationHandler`` converts it into a blocked outcome for
the runtime boundary and appends an audit entry — a violation is always
handled, never silently ignored, and never mutates the underlying stores.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.governance.models import GovernanceDecision, TargetType


class PolicyViolationError(RuntimeError):
    """Raised by the governance engine when a subject is denied."""

    def __init__(self, violation: "PolicyViolation") -> None:
        self.violation = violation
        super().__init__(violation.message)


@dataclass(frozen=True)
class PolicyViolation:
    """Structured description of a governance violation."""

    code: str
    message: str
    target_type: TargetType
    target: str
    decision: Optional[GovernanceDecision] = None
    details: dict[str, Any] = field(default_factory=dict)


class ViolationHandler:
    """Deterministic handling of policy violations at the runtime boundary."""

    def __init__(self, audit: Any = None) -> None:
        self._audit = audit

    def blocked(self, violation: PolicyViolation) -> dict[str, Any]:
        """Return a blocked-outcome payload (never raises)."""
        if self._audit is not None:
            self._audit.record(
                category="violation",
                action=f"{violation.target_type.value}:{violation.target}",
                subject=violation.target,
                result="blocked",
                details={
                    "code": violation.code,
                    "message": violation.message,
                    "decision": violation.decision.model_dump()
                    if violation.decision is not None
                    else None,
                    "extra": violation.details,
                },
            )
        return {
            "governance_blocked": True,
            "governance_violation": violation.code,
            "governance_reason": violation.message,
            "target_type": violation.target_type.value,
            "target": violation.target,
            "extra": violation.details,
        }
