"""Canonical CAP permit gate shared by every runtime execution path.

A Runtime must refuse to execute any task that CAP has not approved
(``ApprovedRuntimeTask.permit``). This module is the single source of
truth for that decision so that no execution path can bypass CAP by
implementing its own (or no) gate.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.contracts import ApprovedRuntimeTask, RoutingDecision, RuntimeResult, RuntimeTask
from app.core.contracts.planning import TaskStatus
from app.core.contracts.pause import ExecutionPause


def enforce_cap_permit(
    task: RuntimeTask,
    routing: RoutingDecision,
    *,
    started_at: datetime,
    duration_ms: float,
) -> RuntimeResult | None:
    """Return a blocking ``RuntimeResult`` when CAP has not approved the task.

    Returns ``None`` when the task carries an ALLOW permit so the caller can
    proceed to execution. Mirrors the single canonical CAP decision shared by
    the RuntimeEngine and the streaming bridge.
    """
    if not isinstance(task, ApprovedRuntimeTask) or task.permit is None:
        return RuntimeResult(
            task_id=task.task_id,
            status=TaskStatus.FAILED,
            routing=routing,
            error="Runtime execution blocked: Task lacks a valid ExecutionPermit from CAP.",
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            duration_ms=duration_ms,
            metadata={"diagnostic": "unapproved_task"},
        )

    if task.permit.decision == "ask_user":
        return RuntimeResult(
            task_id=task.task_id,
            status=TaskStatus.PAUSED,
            routing=routing,
            pause=ExecutionPause(
                reason="cap_approval",
                metadata={"action_type": task.action_type},
            ),
            error="approval required: CAP governance requests user confirmation",
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            duration_ms=duration_ms,
            metadata={"diagnostic": "approval_required"},
        )

    if task.permit.decision != "allow":
        return RuntimeResult(
            task_id=task.task_id,
            status=TaskStatus.FAILED,
            routing=routing,
            error="approval required: CAP governance blocked user request",
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            duration_ms=duration_ms,
            metadata={"diagnostic": "approval_blocked"},
        )

    return None
