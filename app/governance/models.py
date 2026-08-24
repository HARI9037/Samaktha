"""P2.5 — Governance Maturity: policy-as-code data models.

Declarative, machine-readable governance. A ``GovernancePolicy`` is a single
versioned document (loaded from dict/JSON/file) that declares permission
requirements per capability/provider/tool, risk-classification rules,
approval rules and rollback rules — the policy-as-code foundation every other
P2.5 control builds on. Decisions are expressed with the existing
``ApprovalDecision`` and ``ActionRisk`` vocabularies, and runtime permissions
use the canonical ``ToolPermission`` vocabulary shared by ``ToolPolicy``.

``ExecutionRecord`` and ``AuditEntry`` are immutable records (frozen, no
update/delete API) forming an append-only hash chain.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.core.contracts.policy import ActionRisk, ApprovalDecision
from app.tools.framework.models import ToolPermission


class TargetType(StrEnum):
    """The kind of subject a governance rule or decision targets."""

    TOOL = "tool"
    PROVIDER = "provider"
    CAPABILITY = "capability"
    ACTION = "action"


class DecisionStatus(StrEnum):
    """Runtime outcome attached to an immutable execution record."""

    ALLOWED = "allowed"
    BLOCKED = "blocked"
    APPROVAL_REQUIRED = "approval_required"
    EXECUTED = "executed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class PermissionRule(BaseModel):
    """A declared permission/approval requirement for one target."""

    target: str
    permissions: tuple[ToolPermission, ...] = Field(default_factory=tuple)
    approval_required: bool = False


class CapabilityPermissionRule(PermissionRule):
    """Permission requirements for a capability domain."""


class ProviderPermissionRule(PermissionRule):
    """Permission requirements for a communication provider."""


class ToolPermissionRule(PermissionRule):
    """Permission requirements for a tool id."""


class RiskRule(BaseModel):
    """Classify a target (or permission scope) to a risk level."""

    target: str = "*"
    target_type: Optional[TargetType] = None
    risk: ActionRisk
    scopes: tuple[ToolPermission, ...] = Field(default_factory=tuple)


class ApprovalRule(BaseModel):
    """Require (or exempt) approval for a target type/risk threshold."""

    target: str = "*"
    target_type: Optional[TargetType] = None
    risk_at_least: Optional[ActionRisk] = None
    require: bool = True


class RollbackRule(BaseModel):
    """When to force rollback for a target."""

    target: str = "*"
    target_type: Optional[TargetType] = None
    force: bool = False
    when: str = "failure"  # failure | denial | any


class GovernancePolicy(BaseModel):
    """A complete policy-as-code governance document."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str
    version: str
    name: str
    description: str = ""
    default_risk: ActionRisk = ActionRisk.LOW
    default_approval_required: bool = False
    capabilities: list[CapabilityPermissionRule] = Field(default_factory=list)
    providers: list[ProviderPermissionRule] = Field(default_factory=list)
    tools: list[ToolPermissionRule] = Field(default_factory=list)
    risks: list[RiskRule] = Field(default_factory=list)
    approvals: list[ApprovalRule] = Field(default_factory=list)
    rollbacks: list[RollbackRule] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.policy_id}@{self.version}"

    @property
    def identity(self) -> str:
        return self.policy_id

    def rule_for(self, target_type: TargetType, target: str) -> Optional[PermissionRule]:
        """First permission rule matching ``target`` for ``target_type``."""
        rules: dict[TargetType, list[PermissionRule]] = {
            TargetType.TOOL: self.tools,
            TargetType.PROVIDER: self.providers,
            TargetType.CAPABILITY: self.capabilities,
        }
        for rule in rules.get(target_type, ()):
            if rule.target == target:
                return rule
        return None


class GovernanceDecision(BaseModel):
    """Deterministic governance outcome for a single subject."""

    model_config = ConfigDict(frozen=True)

    target_type: TargetType
    target: str
    decision: ApprovalDecision
    risk: ActionRisk
    granted_permissions: tuple[ToolPermission, ...] = Field(default_factory=tuple)
    required_permissions: tuple[ToolPermission, ...] = Field(default_factory=tuple)
    approval_required: bool = False
    policy_id: Optional[str] = None
    policy_hits: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    permit_id: Optional[str] = None
    operation_digest: Optional[str] = None
    authorization_source: Optional[str] = None

    @property
    def allowed(self) -> bool:
        return self.decision == ApprovalDecision.ALLOW


# ---------------------------------------------------------------------------
# Immutable records
# ---------------------------------------------------------------------------


def _chain_hash(previous_hash: str, payload: dict[str, Any]) -> str:
    """sha256 of ``previous_hash`` concatenated with a canonical JSON payload."""
    import hashlib
    import json

    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(f"{previous_hash}|{canonical}".encode("utf-8")).hexdigest()


class ExecutionRecord(BaseModel):
    """Immutable, append-only record of one execution decision/outcome."""

    model_config = ConfigDict(frozen=True)

    record_id: str
    recorded_at: str
    request_id: str
    task_id: str
    target_type: TargetType
    target: str
    decision: str
    risk: str
    status: DecisionStatus
    permissions: tuple[str, ...] = Field(default_factory=tuple)
    error: Optional[str] = None
    permit_id: Optional[str] = None
    operation_digest: Optional[str] = None
    authorization_source: Optional[str] = None
    previous_hash: str = ""
    hash: str = ""

    def recompute_hash(self) -> str:
        return _chain_hash(
            self.previous_hash,
            {
                "record_id": self.record_id,
                "recorded_at": self.recorded_at,
                "request_id": self.request_id,
                "task_id": self.task_id,
                "target_type": self.target_type,
                "target": self.target,
                "decision": self.decision,
                "risk": self.risk,
                "status": self.status,
                "permissions": list(self.permissions),
                "error": self.error,
                "permit_id": self.permit_id,
                "operation_digest": self.operation_digest,
                "authorization_source": self.authorization_source,
                "previous_hash": self.previous_hash,
            },
        )


class AuditEntry(BaseModel):
    """Immutable, append-only governance audit entry."""

    model_config = ConfigDict(frozen=True)

    seq: int
    recorded_at: str
    category: str
    action: str
    subject: str
    result: str
    details: dict[str, Any] = Field(default_factory=dict)
    previous_hash: str = ""
    hash: str = ""

    def recompute_hash(self) -> str:
        return _chain_hash(
            self.previous_hash,
            {
                "seq": self.seq,
                "recorded_at": self.recorded_at,
                "category": self.category,
                "action": self.action,
                "subject": self.subject,
                "result": self.result,
                "details": self.details,
                "previous_hash": self.previous_hash,
            },
        )
