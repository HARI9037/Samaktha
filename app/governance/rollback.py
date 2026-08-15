"""P2.5 — Governance Maturity: rollback/recovery policy.

``RollbackPolicy`` decides whether a failed or denied execution should be
rolled back. A target may declare rollback support (``ToolPolicy.rollback_supported``);
policy ``rollbacks`` rules can force or exempt rollback per target; otherwise
the default is to roll back failed or denied executions only when the target
declares support and the risk is high/critical. This is a decision policy only
— the actual compensating action remains the tool's responsibility.
"""

from __future__ import annotations

from typing import Optional

from app.core.contracts.policy import ActionRisk
from app.governance.models import GovernancePolicy, RollbackRule, TargetType
from app.governance.risk import risk_at_least


class RollbackPolicy:
    """Deterministic rollback/recovery decisions."""

    def should_rollback(
        self,
        *,
        target_type: TargetType,
        target: str,
        rollback_supported: bool = False,
        failed: bool = False,
        denied: bool = False,
        risk: Optional[ActionRisk] = None,
        policy: Optional[GovernancePolicy] = None,
    ) -> tuple[bool, list[str]]:
        """Return ``(rollback, reasons)`` for an execution outcome."""
        if policy is not None:
            for rule in policy.rollbacks:
                if not self._matches_rule(rule, target_type, target):
                    continue
                if rule.when == "denial" and not denied:
                    continue
                if rule.when == "failure" and not failed:
                    continue
                reason = "rollback forced by policy rule" if rule.force else "rollback exempted by policy rule"
                return rule.force, [reason]

        if not rollback_supported:
            return False, ["target does not support rollback"]

        if risk is not None and risk_at_least(risk, ActionRisk.HIGH) and (failed or denied):
            return True, ["high/critical failure or denial with rollback support"]

        if failed:
            return True, ["execution failed and target supports rollback"]
        return False, ["no rollback required"]

    @staticmethod
    def _matches_rule(rule: RollbackRule, target_type: TargetType, target: str) -> bool:
        if rule.target != "*" and rule.target != target:
            return False
        if rule.target_type is not None and rule.target_type != target_type:
            return False
        return True
