from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PrivacyCategory(StrEnum):
    """Privacy categories used before model or runtime routing."""

    PUBLIC = "public"
    INTERNAL = "internal"
    PERSONAL = "personal"
    SENSITIVE = "sensitive"
    CRITICAL = "critical"


class ActionRisk(StrEnum):
    """Risk levels assigned to planned actions."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalDecision(StrEnum):
    """Human approval outcomes returned by approval policy."""

    ALLOW = "allow"
    DENY = "deny"
    ASK_USER = "ask_user"
    STORE_PERMISSION = "store_permission"


class PermissionDecision(StrEnum):
    """Permission lookup result for an action or resource."""

    ALLOWED = "allowed"
    DENIED = "denied"
    UNKNOWN = "unknown"


class PermissionScope(StrEnum):
    """Known permission scopes for trust decisions."""

    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    EXECUTE = "execute"
    NETWORK = "network"
    MODEL_CLOUD = "model_cloud"
    MODEL_LOCAL = "model_local"


class PlannedAction(BaseModel):
    """A planned action submitted for trust evaluation."""

    action_id: str
    action_type: str
    description: str
    target: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    requested_permissions: list[PermissionScope] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PrivacyClassification(BaseModel):
    """Result of privacy classification for text or structured action data."""

    category: PrivacyCategory
    reasons: list[str] = Field(default_factory=list)


class PolicyDecision(BaseModel):
    """Trust boundary decision for one planned action."""

    action_id: str
    allowed: bool
    risk: ActionRisk
    privacy: PrivacyClassification
    required_permissions: list[PermissionScope]
    approval_required: bool
    use_local_model: bool
    reasons: list[str] = Field(default_factory=list)


class ApprovalRequest(BaseModel):
    """Input evaluated by an approval subsystem."""

    action: PlannedAction
    policy: PolicyDecision
    remember_permission: bool = False


class ApprovalOutcome(BaseModel):
    """Decision returned by human-in-the-loop approval logic."""

    decision: ApprovalDecision
    action_id: str
    reasons: list[str] = Field(default_factory=list)


ApprovalResult = ApprovalOutcome


class AmbiguityCandidate(BaseModel):
    """A possible referent for an ambiguous user or planner reference."""

    identifier: str
    label: str
    kind: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AmbiguityCheck(BaseModel):
    """Result of ambiguity detection before execution."""

    ambiguous: bool
    reason: str | None = None
    candidates: list[AmbiguityCandidate] = Field(default_factory=list)


class PermissionRecord(BaseModel):
    """A remembered permission decision."""

    subject_id: str
    resource: str
    scope: PermissionScope
    decision: PermissionDecision
