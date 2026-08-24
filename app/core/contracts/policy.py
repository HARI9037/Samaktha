from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


_PERMIT_SIGNING_KEY = secrets.token_bytes(32)
_PERMIT_LIFETIME = timedelta(minutes=15)
_PERMIT_CLOCK_SKEW = timedelta(seconds=30)


def configure_permit_signing_key(key: bytes) -> None:
    """Configure the process key used to sign and validate durable permits."""
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("ExecutionPermit signing key must contain at least 32 bytes.")
    global _PERMIT_SIGNING_KEY
    _PERMIT_SIGNING_KEY = key
_INCIDENTAL_OPERATION_KEYS = {
    "_cap_permit",
    "plan_task_id",
    "plan_task_kind",
}


class PrivacyCategory(StrEnum):
    """Privacy categories used before model or runtime routing."""

    PUBLIC = "public"
    INTERNAL = "internal"
    PERSONAL = "personal"
    SENSITIVE = "sensitive"
    CRITICAL = "critical"


class ExecutionLocation(StrEnum):
    """Where a provider/model performs inference."""

    LOCAL = "local"
    CLOUD = "cloud"


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


class ExecutionConstraints(BaseModel):
    """CAP-owned requirements that routing and execution must preserve."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requires_local_model: bool = False
    network_allowed: bool = True
    privacy_category: PrivacyCategory = PrivacyCategory.PUBLIC


class PolicyDecision(BaseModel):
    """Trust boundary decision for one planned action."""

    action_id: str
    allowed: bool
    risk: ActionRisk
    privacy: PrivacyClassification
    required_permissions: list[PermissionScope]
    approval_required: bool
    use_local_model: bool
    constraints: ExecutionConstraints = Field(default_factory=ExecutionConstraints)
    reasons: list[str] = Field(default_factory=list)


class ApprovalRequest(BaseModel):
    """Input evaluated by an approval subsystem."""

    action: PlannedAction
    policy: PolicyDecision
    operation: PlannedAction | None = None
    remember_permission: bool = False


class ApprovalOutcome(BaseModel):
    """Decision returned by human-in-the-loop approval logic."""

    decision: ApprovalDecision
    action_id: str
    reasons: list[str] = Field(default_factory=list)


ApprovalResult = ApprovalOutcome


class ApprovalSubmission(BaseModel):
    """A human decision submitted to CAP for a pending action."""

    model_config = ConfigDict(extra="forbid")

    action_id: str
    decision: ApprovalDecision
    reasons: list[str] = Field(default_factory=list)


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


class ExecutionPermit(BaseModel):
    """Signed CAP authorization bound to one exact logical operation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    permit_id: str
    action_id: str
    subject_id: str
    session_id: str | None = None
    workspace_id: str | None = None
    action_type: str
    target: str | None
    operation_digest: str
    required_permissions: tuple[PermissionScope, ...] = Field(default_factory=tuple)
    risk: ActionRisk
    constraints: ExecutionConstraints
    policy_reference: str
    approval_source: str
    approval_provenance: dict[str, Any] = Field(default_factory=dict)
    issued_at: datetime
    expires_at: datetime
    decision: ApprovalDecision
    reasons: list[str] = Field(default_factory=list)
    issued_by: str = "cap.approval_engine"
    integrity_digest: str

    @classmethod
    def issue(
        cls,
        *,
        action: PlannedAction,
        subject_id: str,
        session_id: str | None = None,
        workspace_id: str | None = None,
        policy: PolicyDecision,
        decision: ApprovalDecision,
        reasons: list[str] | None = None,
        approval_source: str = "cap.approval_engine",
        approval_provenance: dict[str, Any] | None = None,
        policy_reference: str = "cap.policy_engine",
        now: datetime | None = None,
    ) -> "ExecutionPermit":
        issued_at = _as_utc(now or datetime.now(timezone.utc))
        values: dict[str, Any] = {
            "permit_id": uuid4().hex,
            "action_id": action.action_id,
            "subject_id": subject_id,
            "session_id": session_id,
            "workspace_id": workspace_id,
            "action_type": normalize_action_type(action.action_type),
            "target": normalize_target(action.target),
            "operation_digest": operation_digest(
                action.action_type,
                action.target,
                action.payload,
            ),
            "required_permissions": tuple(policy.required_permissions),
            "risk": policy.risk,
            "constraints": policy.constraints,
            "policy_reference": policy_reference,
            "approval_source": approval_source,
            "approval_provenance": dict(approval_provenance or {}),
            "issued_at": issued_at,
            "expires_at": issued_at + _PERMIT_LIFETIME,
            "decision": decision,
            "reasons": list(reasons or []),
            "issued_by": "cap.approval_engine",
        }
        return cls(**values, integrity_digest=_sign_permit(values))

    def verify_integrity(self) -> bool:
        values = self.model_dump(exclude={"integrity_digest"})
        return hmac.compare_digest(self.integrity_digest, _sign_permit(values))

    def is_expired(self, now: datetime | None = None) -> bool:
        return _as_utc(now or datetime.now(timezone.utc)) >= _as_utc(self.expires_at)

    def is_not_yet_valid(self, now: datetime | None = None) -> bool:
        """Reject permits issued materially in the future.

        A small skew allowance avoids rejecting legitimate permits at process
        boundaries while preventing a signed, future-dated permit from being
        accepted before its authorization window begins.
        """
        current = _as_utc(now or datetime.now(timezone.utc))
        return current + _PERMIT_CLOCK_SKEW < _as_utc(self.issued_at)

    @classmethod
    def resolve_pending(
        cls,
        pending: "ExecutionPermit",
        *,
        decision: ApprovalDecision,
        reasons: list[str] | None = None,
        approval_source: str = "human",
        approval_provenance: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> "ExecutionPermit":
        """Reissue an intact pending permit with CAP's final human decision."""
        issued_at = _as_utc(now or datetime.now(timezone.utc))
        values = pending.model_dump(exclude={"integrity_digest"})
        values.update(
            {
                "permit_id": uuid4().hex,
                "issued_at": issued_at,
                "expires_at": issued_at + _PERMIT_LIFETIME,
                "decision": decision,
                "reasons": list(reasons or []),
                "approval_source": approval_source,
                "approval_provenance": dict(approval_provenance or {}),
                "issued_by": "cap.approval_engine",
            }
        )
        return cls(**values, integrity_digest=_sign_permit(values))


def normalize_action_type(action_type: str) -> str:
    return action_type.strip().lower().replace("-", "_").replace(" ", "_")


def normalize_target(target: str | None) -> str | None:
    if target is None:
        return None
    normalized = str(target).strip()
    return normalized or None


def normalize_operation_payload(value: Any) -> Any:
    """Return a stable JSON-compatible operation payload.

    Only known workflow bookkeeping fields are excluded. User arguments,
    prompts, paths, commands, and tool actions remain authorization-relevant.
    """
    if isinstance(value, BaseModel):
        return normalize_operation_payload(value.model_dump())
    if isinstance(value, dict):
        return {
            str(key): normalize_operation_payload(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _INCIDENTAL_OPERATION_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [normalize_operation_payload(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return _as_utc(value).isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def operation_digest(
    action_type: str,
    target: str | None,
    payload: dict[str, Any] | None,
) -> str:
    canonical = {
        "action_type": normalize_action_type(action_type),
        "target": normalize_target(target),
        "payload": normalize_operation_payload(payload or {}),
    }
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def authorization_payload(
    action_type: str,
    inputs: dict[str, Any] | None,
) -> dict[str, Any]:
    """Select execution inputs that define the approved logical operation."""
    payload = dict(inputs or {})
    messages = payload.pop("messages", None)  # Runtime-derived context expansion.
    payload.pop("prepared_context", None)  # Typed P3 context/evidence boundary.
    if normalize_action_type(action_type) in {
        "text_generation",
        "code_generation",
        "provider",
    }:
        # Workflow may prepend trusted tool evidence after CAP issuance. Bind
        # the permit to the unchanged user request at the explicit delimiter,
        # not to incidental evidence text that only exists after execution.
        prompt = payload.get("prompt")
        marker = "[USER REQUEST]\n"
        if messages and isinstance(prompt, str) and marker in prompt:
            payload["prompt"] = prompt.rsplit(marker, 1)[-1]
    else:
        payload.pop("prompt", None)
        payload.pop("system_prompt", None)
    return payload


def authorization_target(action_type: str, tool_id: str | None = None) -> str:
    normalized = normalize_action_type(action_type)
    if normalized in {"text_generation", "code_generation", "provider"}:
        return f"provider:{normalized}"
    return normalize_target(tool_id) or normalized


def authorization_subject_id(
    *,
    user_id: str | None,
    session_id: str | None,
    request_id: str,
) -> str:
    """Stable principal selection shared by CAP and Runtime."""
    return user_id or session_id or request_id


def _sign_permit(values: dict[str, Any]) -> str:
    canonical = normalize_operation_payload(values)
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hmac.new(_PERMIT_SIGNING_KEY, encoded, hashlib.sha256).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
