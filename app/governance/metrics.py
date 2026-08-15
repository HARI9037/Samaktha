"""P2.7 — Governance metrics.

Deterministic in-memory observability for the governance engine: how many
evaluations ran, how decisions split across allow / ask-user / deny, and how
often the engine blocked subjects, audited violations, and decided rollbacks.
Recording is purely additive — it never changes a governance outcome.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.core.contracts.policy import ApprovalDecision


class GovernanceMetricsSnapshot(BaseModel):
    """Read-only snapshot of governance engine metrics."""

    evaluations: int = 0
    allow_decisions: int = 0
    ask_user_decisions: int = 0
    deny_decisions: int = 0
    blocks: int = 0
    violations: int = 0
    rollbacks: int = 0


class GovernanceMetricsCollector:
    """Deterministic in-memory metrics for ``GovernanceEngine``."""

    def __init__(self) -> None:
        self._evaluations = 0
        self._allow = 0
        self._ask_user = 0
        self._deny = 0
        self._blocks = 0
        self._violations = 0
        self._rollbacks = 0

    def record_evaluation(self, decision: str, *, approval_required: bool = False) -> None:
        self._evaluations += 1
        if decision == ApprovalDecision.ALLOW.value:
            self._allow += 1
        elif decision == ApprovalDecision.DENY.value:
            self._deny += 1
        elif decision == ApprovalDecision.ASK_USER.value:
            self._ask_user += 1
        elif approval_required:
            self._ask_user += 1

    def record_block(self) -> None:
        self._blocks += 1

    def record_violation(self) -> None:
        self._violations += 1

    def record_rollback(self) -> None:
        self._rollbacks += 1

    def get_metrics(self) -> GovernanceMetricsSnapshot:
        return GovernanceMetricsSnapshot(
            evaluations=self._evaluations,
            allow_decisions=self._allow,
            ask_user_decisions=self._ask_user,
            deny_decisions=self._deny,
            blocks=self._blocks,
            violations=self._violations,
            rollbacks=self._rollbacks,
        )
