"""Canonical CAP permit gate shared by every runtime execution path.

A Runtime must refuse to execute any task that CAP has not approved
(``ApprovedRuntimeTask.permit``). This module is the single source of
truth for that decision so that no execution path can bypass CAP by
implementing its own (or no) gate.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.contracts import ApprovedRuntimeTask, RoutingDecision, RuntimeContext, RuntimeResult, RuntimeTask
from app.core.contracts.planning import TaskStatus
from app.core.contracts.pause import ExecutionPause
from app.core.contracts.policy import (
    ApprovalDecision,
    ExecutionConstraints,
    authorization_payload,
    authorization_subject_id,
    authorization_target,
    operation_digest,
)
from app.evidence.sanitizer import sanitize_for_evidence


_APPROVAL_ARGUMENT_KEYS = {
    "action",
    "path",
    "target_path",
    "source",
    "destination",
    "query",
    "recipient",
    "to",
    "subject",
    "title",
    "executable",
    "args",
    "command",
    "host",
    "url",
    "due_at",
    "datetime",
    "name",
    "amount",
    "value",
}


def _approval_argument_summary(inputs: dict) -> dict:
    selected = {
        str(key): value
        for key, value in inputs.items()
        if str(key).lower() in _APPROVAL_ARGUMENT_KEYS
    }
    sanitized = sanitize_for_evidence(selected)
    if not isinstance(sanitized, dict):
        return {}
    bounded: dict = {}
    for key, value in sanitized.items():
        if isinstance(value, list):
            bounded[key] = [str(item)[:200] for item in value[:20]]
        elif isinstance(value, dict):
            bounded[key] = {
                str(child_key)[:80]: str(child_value)[:200]
                for child_key, child_value in list(value.items())[:20]
            }
        else:
            bounded[key] = str(value)[:500]
    return bounded


def enforce_cap_permit(
    task: RuntimeTask,
    routing: RoutingDecision,
    *,
    started_at: datetime,
    duration_ms: float,
    context: RuntimeContext | None = None,
) -> RuntimeResult | None:
    """Return a blocking ``RuntimeResult`` when CAP has not approved the task.

    Returns ``None`` when the task carries an ALLOW permit so the caller can
    proceed to execution. Mirrors the single canonical CAP decision shared by
    the RuntimeEngine and the streaming bridge.
    """
    if not isinstance(task, ApprovedRuntimeTask) or task.permit is None:
        return _blocked(
            task, routing, started_at, duration_ms,
            "unapproved_task",
            "Runtime execution blocked: Task lacks a valid ExecutionPermit from CAP.",
        )

    permit = task.permit
    authorization = {
        "permit_id": permit.permit_id,
        "operation_digest": permit.operation_digest,
        "authorization_decision": permit.decision.value,
        "authorization_source": permit.approval_source,
        "policy_reference": permit.policy_reference,
    }

    if permit.decision == ApprovalDecision.ASK_USER:
        approval_metadata = {
            "action_type": task.action_type,
            "action": task.inputs.get("action") or task.action_type,
            "target": permit.target,
            "tool": task.metadata.get("tool"),
            "args": _approval_argument_summary(task.inputs),
            "risk": permit.risk.value,
            "permissions": [scope.value for scope in permit.required_permissions],
            "operation_digest": permit.operation_digest,
        }
        return RuntimeResult(
            task_id=task.task_id,
            status=TaskStatus.PAUSED,
            routing=routing,
            pause=ExecutionPause(
                reason="cap_approval",
                metadata=approval_metadata,
            ),
            error="approval required: CAP governance requests user confirmation",
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            duration_ms=duration_ms,
            metadata={"diagnostic": "approval_required", **authorization},
        )

    if permit.decision != ApprovalDecision.ALLOW:
        return _blocked(
            task, routing, started_at, duration_ms,
            "approval_blocked",
            "approval required: CAP governance blocked user request",
            authorization,
        )

    if not permit.verify_integrity():
        return _blocked(
            task, routing, started_at, duration_ms,
            "permit_integrity_invalid",
            "Runtime execution blocked: ExecutionPermit integrity validation failed.",
            authorization,
        )
    if permit.is_not_yet_valid():
        return _blocked(
            task, routing, started_at, duration_ms,
            "permit_not_yet_valid",
            "Runtime execution blocked: ExecutionPermit is not yet valid.",
            authorization,
        )
    if permit.is_expired():
        return _blocked(
            task, routing, started_at, duration_ms,
            "permit_expired",
            "Runtime execution blocked: ExecutionPermit has expired.",
            authorization,
        )

    # Identity carried by the typed RuntimeContext is authoritative. Metadata
    # is a compatibility fallback only when no principal/session is present;
    # otherwise a caller could use it to mask an actual principal mismatch.
    derived_subject = authorization_subject_id(
        user_id=context.user_id if context else None,
        session_id=context.session_id if context else None,
        request_id=context.request_id if context else task.task_id,
    )
    metadata_subject = (
        context.metadata.get("authorization_subject_id")
        if context is not None
        else None
    )
    expected_subject = (
        derived_subject
        if context is None or context.user_id or context.session_id
        else metadata_subject or derived_subject
    )
    if permit.subject_id != expected_subject:
        return _blocked(
            task, routing, started_at, duration_ms,
            "permit_subject_mismatch",
            "Runtime execution blocked: ExecutionPermit subject does not match.",
            authorization,
        )
    if permit.session_id is not None and (
        context is None or context.session_id != permit.session_id
    ):
        return _blocked(
            task, routing, started_at, duration_ms,
            "permit_session_mismatch",
            "Runtime execution blocked: ExecutionPermit session does not match.",
            authorization,
        )
    context_workspace = context.workspace_id if context is not None else None
    if permit.workspace_id is not None and context_workspace != permit.workspace_id:
        return _blocked(
            task, routing, started_at, duration_ms,
            "permit_workspace_mismatch",
            "Runtime execution blocked: ExecutionPermit workspace does not match.",
            authorization,
        )
    if permit.action_id != task.task_id:
        return _blocked(
            task, routing, started_at, duration_ms,
            "permit_action_mismatch",
            "Runtime execution blocked: ExecutionPermit action does not match.",
            authorization,
        )

    tool_id = task.metadata.get("tool") if task.action_type == "tool" else None
    target = authorization_target(task.action_type, tool_id)
    digest = operation_digest(
        task.action_type,
        target,
        authorization_payload(task.action_type, task.inputs),
    )
    if (
        permit.action_type != task.action_type
        or permit.target != target
        or permit.operation_digest != digest
    ):
        return _blocked(
            task, routing, started_at, duration_ms,
            "permit_operation_mismatch",
            "Runtime execution blocked: ExecutionPermit operation binding does not match.",
            authorization,
        )

    metadata_permissions = tuple(task.metadata.get("required_permissions", ()))
    if metadata_permissions != tuple(scope.value for scope in permit.required_permissions):
        return _blocked(
            task, routing, started_at, duration_ms,
            "permit_permissions_mismatch",
            "Runtime execution blocked: ExecutionPermit permissions do not match.",
            authorization,
        )

    try:
        task_constraints = ExecutionConstraints.model_validate(
            task.metadata.get("execution_constraints", {})
        )
    except Exception:
        task_constraints = None
    if task_constraints != permit.constraints:
        return _blocked(
            task, routing, started_at, duration_ms,
            "permit_constraints_mismatch",
            "Runtime execution blocked: ExecutionPermit constraints do not match.",
            authorization,
        )
    if task.action_type in {"text_generation", "code_generation", "provider"}:
        if routing.execution_constraints != permit.constraints:
            return _blocked(
                task, routing, started_at, duration_ms,
                "routing_constraints_mismatch",
                "Runtime execution blocked: Router did not preserve CAP constraints.",
                authorization,
            )

    return None


def authorization_metadata(task: RuntimeTask) -> dict[str, str]:
    if not isinstance(task, ApprovedRuntimeTask) or task.permit is None:
        return {}
    permit = task.permit
    return {
        "permit_id": permit.permit_id,
        "operation_digest": permit.operation_digest,
        "authorization_decision": permit.decision.value,
        "authorization_source": permit.approval_source,
        "policy_reference": permit.policy_reference,
    }


def _blocked(
    task: RuntimeTask,
    routing: RoutingDecision,
    started_at: datetime,
    duration_ms: float,
    diagnostic: str,
    error: str,
    metadata: dict | None = None,
) -> RuntimeResult:
    return RuntimeResult(
        task_id=task.task_id,
        status=TaskStatus.FAILED,
        routing=routing,
        error=error,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        duration_ms=duration_ms,
        metadata={"diagnostic": diagnostic, **(metadata or {})},
    )
