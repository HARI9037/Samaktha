"""P2.5 — Governance Maturity: declarative approval policies.

``ApprovalPolicyEngine`` decides whether a governance subject requires
explicit human approval. Policy ``approvals`` rules take precedence (first
match), then an explicit per-target rule flag, then the risk threshold
(high/critical requires approval), then the policy's default. Decisions use
the existing ``ApprovalDecision`` vocabulary (allow / ask_user / deny).
"""

from __future__ import annotations

from typing import Optional

from app.core.contracts.policy import ActionRisk, ApprovalDecision
from app.governance.models import ApprovalRule, GovernancePolicy, TargetType
from app.governance.risk import risk_at_least


class ApprovalPolicyEngine:
    """Deterministic approval-required decisions from policy rules."""

    def required(
        self,
        target_type: TargetType,
        target: str,
        risk: ActionRisk,
        *,
        policy: Optional[GovernancePolicy] = None,
        rule_approval: Optional[bool] = None,
    ) -> tuple[bool, list[str]]:
        """Return ``(approval_required, reasons)``."""
        if policy is not None:
            for rule in policy.approvals:
                if not self._matches_rule(rule, target_type, target, risk):
                    continue
                reason = (
                    "approval required by policy rule"
                    if rule.require
                    else "approval exempted by policy rule"
                )
                return rule.require, [reason]

        if rule_approval is not None:
            return rule_approval, ["target permission rule requires approval"]

        if risk_at_least(risk, ActionRisk.HIGH):
            return True, ["high/critical risk requires approval"]

        default = policy.default_approval_required if policy is not None else False
        if default:
            return True, ["policy default requires approval"]
        return False, ["no approval required"]

    def decision(
        self,
        target_type: TargetType,
        target: str,
        risk: ActionRisk,
        *,
        denied_permissions: tuple = (),
        policy: Optional[GovernancePolicy] = None,
        rule_approval: Optional[bool] = None,
    ) -> tuple[ApprovalDecision, list[str]]:
        """Derive an ``ApprovalDecision`` from the approval policy."""
        if denied_permissions:
            missing = ", ".join(p.value for p in denied_permissions)
            return ApprovalDecision.DENY, [f"missing granted permission(s): {missing}"]

        approval_required, reasons = self.required(
            target_type, target, risk, policy=policy, rule_approval=rule_approval
        )
        if approval_required:
            reasons.append("human approval requested")
            return ApprovalDecision.ASK_USER, reasons
        return ApprovalDecision.ALLOW, reasons

    @staticmethod
    def _matches_rule(
        rule: ApprovalRule,
        target_type: TargetType,
        target: str,
        risk: ActionRisk,
    ) -> bool:
        if rule.target != "*" and rule.target != target:
            return False
        if rule.target_type is not None and rule.target_type != target_type:
            return False
        if rule.risk_at_least is not None and not risk_at_least(risk, rule.risk_at_least):
            return False
        return True
