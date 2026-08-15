"""P2.5 — Governance Maturity: deterministic risk classification.

Classifies a governance subject (tool / provider / capability / action) to an
``ActionRisk`` level. Policy ``risks`` rules take precedence (first match);
otherwise deterministic scope defaults apply: destructive (admin/delete)
permissions are CRITICAL, execute/network are HIGH, write/modify are MEDIUM,
and anything else is LOW unless approval is required.
"""

from __future__ import annotations

from typing import Iterable, Optional

from app.core.contracts.policy import ActionRisk
from app.governance.models import GovernancePolicy, TargetType
from app.tools.framework.models import ToolPermission

_RISK_RANK = {level: rank for rank, level in enumerate(ActionRisk)}


class RiskClassifier:
    """Deterministic mapping of subjects to risk levels."""

    def classify(
        self,
        target_type: TargetType,
        target: str,
        *,
        permissions: Iterable[ToolPermission] = (),
        approval_required: bool = False,
        policy: Optional[GovernancePolicy] = None,
    ) -> tuple[ActionRisk, list[str]]:
        """Return ``(risk, reasons)`` for a subject."""
        permissions = list(permissions)
        default = policy.default_risk if policy is not None else ActionRisk.LOW

        if policy is not None:
            for rule in policy.risks:
                if not self._matches_rule(rule.target, rule.target_type, target_type, target):
                    continue
                if rule.scopes and not any(p in rule.scopes for p in permissions):
                    continue
                return rule.risk, [f"risk rule '{rule.target}' matched"]

        if any(p in (ToolPermission.ADMIN, ToolPermission.DELETE) for p in permissions):
            return ActionRisk.CRITICAL, ["destructive permission declared"]
        if approval_required or any(p in (ToolPermission.EXECUTE, ToolPermission.NETWORK) for p in permissions):
            return ActionRisk.HIGH, (
                ["approval is required"]
                if approval_required
                else ["execute/network permission declared"]
            )
        if any(p in (ToolPermission.WRITE, ToolPermission.MODIFY) for p in permissions):
            return ActionRisk.MEDIUM, ["write/modify permission declared"]
        return default, ["default risk applied"]

    @staticmethod
    def _matches_rule(
        rule_target: str,
        rule_type: Optional[TargetType],
        target_type: TargetType,
        target: str,
    ) -> bool:
        if rule_target != "*" and rule_target != target:
            return False
        if rule_type is not None and rule_type != target_type:
            return False
        return True


def risk_at_least(risk: ActionRisk, threshold: ActionRisk) -> bool:
    """True when ``risk`` ranks at or above ``threshold``."""
    return _RISK_RANK[risk] >= _RISK_RANK[threshold]


def security_level_for(risk: ActionRisk) -> str:
    """Map an ``ActionRisk`` to the security vocabulary used by ToolGuard."""
    return risk.value
