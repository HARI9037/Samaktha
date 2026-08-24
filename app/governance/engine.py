"""P2.5 — Governance Maturity: the governance engine.

``GovernanceEngine`` is the single entry point for policy evaluation and
enforcement across tools, providers and capabilities. It composes the
policy registry, risk classifier, approval policy, immutable execution
records, audit trail and violation handler into one deterministic control:

  1. resolve the active policy;
  2. find the permission rule for the subject;
  3. classify risk;
  4. compute granted permissions and detect denied ones;
  5. decide approval (allow / ask_user / deny);
  6. audit every decision and record every execution immutably.

Without any registered policy the engine is permissive: a subject is granted
exactly its declared permissions (so the canonical runtime behavior is
preserved) and only explicit rules restrict it.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from app.core.contracts.policy import ApprovalDecision, ExecutionPermit
from app.governance.approval import ApprovalPolicyEngine
from app.governance.audit import GovernanceAuditLog
from app.governance.metrics import GovernanceMetricsCollector, GovernanceMetricsSnapshot
from app.governance.models import (
    DecisionStatus,
    ExecutionRecord,
    GovernanceDecision,
    GovernancePolicy,
    TargetType,
)
from app.governance.policy import PolicyRegistry
from app.governance.records import ExecutionRecordStore, build_execution_record
from app.governance.risk import RiskClassifier
from app.governance.rollback import RollbackPolicy
from app.governance.violations import (
    PolicyViolation,
    PolicyViolationError,
    ViolationHandler,
)
from app.tools.framework.models import ToolPermission


class GovernanceEngine:
    """Orchestrates policy evaluation, enforcement and recording."""

    def __init__(
        self,
        registry: Optional[PolicyRegistry] = None,
        *,
        default_policy_id: Optional[str] = None,
        risk: Optional[RiskClassifier] = None,
        approval: Optional[ApprovalPolicyEngine] = None,
        records: Optional[ExecutionRecordStore] = None,
        audit: Optional[GovernanceAuditLog] = None,
        violations: Optional[ViolationHandler] = None,
        rollback: Optional[RollbackPolicy] = None,
        metrics: Optional[GovernanceMetricsCollector] = None,
    ) -> None:
        self.registry = registry or PolicyRegistry()
        self._default_policy_id = default_policy_id
        self.risk = risk or RiskClassifier()
        self.approval = approval or ApprovalPolicyEngine()
        self.records = records or ExecutionRecordStore()
        self.audit = audit or GovernanceAuditLog()
        self.violations = violations or ViolationHandler(self.audit)
        self.rollback = rollback or RollbackPolicy()
        self._metrics = metrics or GovernanceMetricsCollector()

    # ------------------------------------------------------------------
    # Policy resolution
    # ------------------------------------------------------------------

    @property
    def default_policy_id(self) -> Optional[str]:
        return self._default_policy_id

    def set_default_policy(self, policy: GovernancePolicy) -> None:
        """Make ``policy`` the active policy for evaluations without an
        explicit ``policy_id``."""
        self.registry.register(policy)
        self._default_policy_id = policy.key

    def _resolve_policy(self, policy_id: Optional[str]) -> Optional[GovernancePolicy]:
        resolved = policy_id or self._default_policy_id
        if resolved is None:
            return None
        if self.registry.has(resolved):
            return self.registry.get(resolved)
        return self.registry.latest(resolved)

    def active_policies(self) -> list[GovernancePolicy]:
        return self.registry.list()

    def get_metrics(self) -> GovernanceMetricsSnapshot:
        return self._metrics.get_metrics()

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        target_type: TargetType,
        target: str,
        *,
        declared_permissions: Iterable[ToolPermission] = (),
        requested_permissions: Iterable[ToolPermission] = (),
        policy_id: Optional[str] = None,
        subject: Optional[str] = None,
        grant_from_declared: bool = False,
        permit: ExecutionPermit | None = None,
    ) -> GovernanceDecision:
        """Evaluate governance for a single subject and audit the decision.

        ``grant_from_declared`` is used for capability subjects, where the
        capability's permission rule declares what a provider tool *must
        have* rather than what is granted: the granted set is the tool's
        declared permissions and the rule's permissions are the required set.
        """
        policy = self._resolve_policy(policy_id)
        declared = _dedupe(declared_permissions)
        requested = _dedupe(requested_permissions)

        rule = policy.rule_for(target_type, target) if policy is not None else None
        if rule is not None and not grant_from_declared:
            granted = _dedupe(rule.permissions)
        else:
            granted = declared

        combined = _dedupe((*declared, *requested))
        denied = tuple(p for p in combined if p not in granted)

        risk, risk_reasons = self.risk.classify(
            target_type,
            target,
            permissions=combined,
            approval_required=rule.approval_required if rule is not None else False,
            policy=policy,
        )

        rule_approval = rule.approval_required if rule is not None else None
        decision, approval_reasons = self.approval.decision(
            target_type,
            target,
            risk,
            denied_permissions=denied,
            policy=policy,
            rule_approval=rule_approval,
        )

        policy_hits = risk_reasons + approval_reasons
        if permit is not None:
            permit_valid = (
                permit.verify_integrity()
                and not permit.is_expired()
                and permit.decision == ApprovalDecision.ALLOW
                and (subject is None or permit.subject_id == subject)
            )
            if not permit_valid:
                decision = ApprovalDecision.DENY
                policy_hits = [*policy_hits, "invalid CAP ExecutionPermit"]
            elif decision == ApprovalDecision.ASK_USER:
                decision = ApprovalDecision.ALLOW
                policy_hits = [
                    *policy_hits,
                    "human approval satisfied by exact CAP ExecutionPermit",
                ]
        outcome = GovernanceDecision(
            target_type=target_type,
            target=target,
            decision=decision,
            risk=risk,
            granted_permissions=granted,
            required_permissions=_dedupe(rule.permissions) if rule is not None else (),
            approval_required=decision == ApprovalDecision.ASK_USER,
            policy_id=policy.key if policy is not None else None,
            policy_hits=policy_hits,
            reasons=policy_hits,
            permit_id=permit.permit_id if permit else None,
            operation_digest=permit.operation_digest if permit else None,
            authorization_source=permit.approval_source if permit else None,
        )

        self.audit.record(
            category="governance",
            action=f"{target_type.value}:{target}",
            subject=subject or target,
            result=decision.value,
            details={
                "risk": risk.value,
                "granted_permissions": [p.value for p in granted],
                "denied_permissions": [p.value for p in denied],
                "policy_id": policy.key if policy is not None else None,
                "reasons": policy_hits,
                "permit_id": permit.permit_id if permit else None,
                "operation_digest": permit.operation_digest if permit else None,
                "authorization_source": permit.approval_source if permit else None,
            },
        )
        self._metrics.record_evaluation(
            decision.value, approval_required=decision == ApprovalDecision.ASK_USER
        )
        return outcome

    # ------------------------------------------------------------------
    # Enforcement
    # ------------------------------------------------------------------

    def enforce_tool(
        self,
        tool_id: str,
        *,
        declared_permissions: Iterable[ToolPermission] = (),
        requested_permissions: Iterable[ToolPermission] = (),
        policy_id: Optional[str] = None,
        subject: Optional[str] = None,
        permit: ExecutionPermit | None = None,
    ) -> GovernanceDecision:
        """Evaluate tool governance; raises ``PolicyViolationError`` when denied."""
        decision = self.evaluate(
            TargetType.TOOL,
            tool_id,
            declared_permissions=declared_permissions,
            requested_permissions=requested_permissions,
            policy_id=policy_id,
            subject=subject,
            permit=permit,
        )
        if not decision.allowed:
            self._metrics.record_block()
            raise PolicyViolationError(
                PolicyViolation(
                    code="permission_denied",
                    message=self._denial_message(decision),
                    target_type=TargetType.TOOL,
                    target=tool_id,
                    decision=decision,
                )
            )
        return decision

    def enforce_capability(
        self,
        capability: str,
        tool_id: str,
        *,
        declared_permissions: Iterable[ToolPermission] = (),
        policy_id: Optional[str] = None,
        subject: Optional[str] = None,
        permit: ExecutionPermit | None = None,
    ) -> GovernanceDecision:
        """Evaluate capability governance; the providing tool's declared
        permissions must cover the capability's required permissions."""
        decision = self.evaluate(
            TargetType.CAPABILITY,
            capability,
            declared_permissions=declared_permissions,
            requested_permissions=(),
            policy_id=policy_id,
            subject=subject,
            permit=permit,
            grant_from_declared=True,
        )
        if decision.required_permissions and not _covers(
            decision.granted_permissions, decision.required_permissions
        ):
            missing = ", ".join(
                p.value
                for p in decision.required_permissions
                if p not in decision.granted_permissions
            )
            self._metrics.record_block()
            raise PolicyViolationError(
                PolicyViolation(
                    code="capability_permissions_missing",
                    message=(
                        f"Capability '{capability}' (tool '{tool_id}') requires "
                        f"permission(s): {missing}"
                    ),
                    target_type=TargetType.CAPABILITY,
                    target=capability,
                    decision=decision,
                )
            )
        if not decision.allowed:
            self._metrics.record_block()
            raise PolicyViolationError(
                PolicyViolation(
                    code="permission_denied",
                    message=self._denial_message(decision),
                    target_type=TargetType.CAPABILITY,
                    target=capability,
                    decision=decision,
                )
            )
        return decision

    def enforce_provider(
        self,
        provider_id: str,
        *,
        requested_permissions: Iterable[ToolPermission] = (),
        policy_id: Optional[str] = None,
        subject: Optional[str] = None,
        permit: ExecutionPermit | None = None,
    ) -> GovernanceDecision:
        """Evaluate provider governance; raises ``PolicyViolationError`` when denied."""
        decision = self.evaluate(
            TargetType.PROVIDER,
            provider_id,
            declared_permissions=(),
            requested_permissions=requested_permissions,
            policy_id=policy_id,
            subject=subject,
            permit=permit,
        )
        if not decision.allowed:
            self._metrics.record_block()
            raise PolicyViolationError(
                PolicyViolation(
                    code="provider_blocked",
                    message=self._denial_message(decision),
                    target_type=TargetType.PROVIDER,
                    target=provider_id,
                    decision=decision,
                )
            )
        return decision

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_execution(
        self,
        decision: GovernanceDecision,
        *,
        request_id: str,
        task_id: str,
        status: DecisionStatus,
        error: Optional[str] = None,
        subject: Optional[str] = None,
    ) -> ExecutionRecord:
        """Append an immutable execution record and audit the outcome."""
        record = build_execution_record(
            request_id=request_id,
            task_id=task_id,
            target_type=decision.target_type,
            target=decision.target,
            decision=decision.decision.value,
            risk=decision.risk.value,
            status=status,
            permissions=tuple(p.value for p in decision.granted_permissions),
            error=error,
            permit_id=decision.permit_id,
            operation_digest=decision.operation_digest,
            authorization_source=decision.authorization_source,
        )
        sealed = self.records.append(record)
        self.audit.record(
            category="execution",
            action=f"{decision.target_type.value}:{decision.target}",
            subject=subject or decision.target,
            result=status.value,
            details={
                "record_id": sealed.record_id,
                "decision": decision.decision.value,
                "risk": decision.risk.value,
                "error": error,
                "permit_id": decision.permit_id,
                "operation_digest": decision.operation_digest,
                "authorization_source": decision.authorization_source,
            },
        )
        return sealed

    def violation(self, code: str, message: str, decision: GovernanceDecision) -> PolicyViolation:
        """Create and audit a policy violation for ``decision``."""
        violation = PolicyViolation(
            code=code,
            message=message,
            target_type=decision.target_type,
            target=decision.target,
            decision=decision,
        )
        self._metrics.record_violation()
        self.audit.record(
            category="violation",
            action=f"{decision.target_type.value}:{decision.target}",
            subject=decision.target,
            result="blocked",
            details={"code": code, "message": message},
        )
        return violation

    def should_rollback(
        self,
        *,
        target_type: TargetType,
        target: str,
        rollback_supported: bool = False,
        failed: bool = False,
        denied: bool = False,
        risk: Optional[Any] = None,
        policy_id: Optional[str] = None,
    ) -> tuple[bool, list[str]]:
        """Rollback/recovery decision for an execution outcome, resolving the
        active policy through this engine."""
        policy = self._resolve_policy(policy_id)
        decided, reasons = self.rollback.should_rollback(
            target_type=target_type,
            target=target,
            rollback_supported=rollback_supported,
            failed=failed,
            denied=denied,
            risk=risk,
            policy=policy,
        )
        if decided:
            self._metrics.record_rollback()
        return decided, reasons

    def blocked_payload(self, violation: PolicyViolation) -> dict[str, Any]:
        """Materialize a blocked-outcome payload for the runtime boundary."""
        return self.violations.blocked(violation)

    # ------------------------------------------------------------------

    @staticmethod
    def _denial_message(decision: GovernanceDecision) -> str:
        reasons = "; ".join(decision.reasons) if decision.reasons else decision.decision.value
        return (
            f"Governance {decision.decision.value} for "
            f"{decision.target_type.value} '{decision.target}': {reasons}"
        )


def _dedupe(values: Iterable[ToolPermission]) -> tuple[ToolPermission, ...]:
    return tuple(dict.fromkeys(values))


def _covers(granted: tuple[ToolPermission, ...], required: tuple[ToolPermission, ...]) -> bool:
    return all(p in granted for p in required)
