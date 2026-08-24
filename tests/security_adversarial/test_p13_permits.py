from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.cap.approval_engine import ApprovalEngine
from app.core.contracts import ApprovedRuntimeTask, RoutingDecision, RuntimeContext
from app.core.contracts.policy import (
    ApprovalDecision,
    ApprovalSubmission,
    ExecutionConstraints,
    ExecutionPermit,
    PrivacyCategory,
)
from tests.conftest import approved_task


def _routing(task: ApprovedRuntimeTask) -> RoutingDecision:
    assert task.permit is not None
    return RoutingDecision(
        provider_id="mock",
        model_id="mock-model",
        reasoning_summary="P13 adversarial permit validation",
        execution_constraints=task.permit.constraints,
    )


def _task(*, subject_id: str = "principal-a") -> ApprovedRuntimeTask:
    return approved_task(
        task_id="p13-bound-task",
        action_type="text_generation",
        inputs={"prompt": "authorized operation"},
        subject_id=subject_id,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("permit_id", "stolen-permit-id"),
        ("action_id", "different-action"),
        ("subject_id", "principal-b"),
        ("action_type", "code_generation"),
        ("target", "provider:code_generation"),
        ("operation_digest", "0" * 64),
        ("required_permissions", ("network",)),
        ("risk", "critical"),
        (
            "constraints",
            ExecutionConstraints(
                requires_local_model=True,
                network_allowed=False,
                privacy_category=PrivacyCategory.CRITICAL,
            ),
        ),
        ("policy_reference", "attacker-policy"),
        ("approval_source", "attacker"),
        ("approval_provenance", {"human_submission": False}),
        ("issued_at", datetime(2000, 1, 1, tzinfo=timezone.utc)),
        ("expires_at", datetime(2999, 1, 1, tzinfo=timezone.utc)),
        ("issued_by", "attacker"),
        ("integrity_digest", "random"),
    ],
)
async def test_signed_permit_field_tampering_never_dispatches_provider(
    production_orchestrator,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement,
) -> None:
    task = _task()
    assert task.permit is not None
    task.permit = task.permit.model_copy(update={field: replacement})
    provider = production_orchestrator.provider_manager.resolve_provider("mock")
    calls = 0

    async def execute(_payload):
        nonlocal calls
        calls += 1
        return {"success": True, "response": "should not execute"}

    monkeypatch.setattr(provider, "execute", execute)
    result = await production_orchestrator.runtime.run(
        RuntimeContext(request_id="request", user_id="principal-a"),
        task,
        _routing(task),
    )

    assert result.status.value == "failed"
    assert calls == 0


@pytest.mark.asyncio
async def test_context_metadata_cannot_override_actual_principal(
    production_orchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task(subject_id="principal-a")
    provider = production_orchestrator.provider_manager.resolve_provider("mock")
    calls = 0

    async def execute(_payload):
        nonlocal calls
        calls += 1
        return {"success": True, "response": "should not execute"}

    monkeypatch.setattr(provider, "execute", execute)
    result = await production_orchestrator.runtime.run(
        RuntimeContext(
            request_id="request",
            user_id="principal-b",
            metadata={"authorization_subject_id": "principal-a"},
        ),
        task,
        _routing(task),
    )

    assert result.metadata["diagnostic"] == "permit_subject_mismatch"
    assert calls == 0


@pytest.mark.asyncio
async def test_future_dated_signed_permit_is_not_yet_valid(
    production_orchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task()
    assert task.permit is not None
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    task.permit = ExecutionPermit.resolve_pending(
        task.permit,
        decision=ApprovalDecision.ALLOW,
        now=future,
    )
    provider = production_orchestrator.provider_manager.resolve_provider("mock")
    calls = 0

    async def execute(_payload):
        nonlocal calls
        calls += 1
        return {"success": True, "response": "should not execute"}

    monkeypatch.setattr(provider, "execute", execute)
    result = await production_orchestrator.runtime.run(
        RuntimeContext(request_id="request", user_id="principal-a"),
        task,
        _routing(task),
    )

    assert result.metadata["diagnostic"] == "permit_not_yet_valid"
    assert calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("runtime_session", "runtime_workspace", "diagnostic"),
    [
        ("session-b", "workspace-a", "permit_session_mismatch"),
        ("session-a", "workspace-b", "permit_workspace_mismatch"),
    ],
)
async def test_permit_is_bound_to_session_and_workspace(
    production_orchestrator,
    monkeypatch: pytest.MonkeyPatch,
    runtime_session: str,
    runtime_workspace: str,
    diagnostic: str,
) -> None:
    task = approved_task(
        task_id="p13-scoped-task",
        action_type="text_generation",
        inputs={"prompt": "authorized operation"},
        subject_id="principal-a",
        permit_session_id="session-a",
        permit_workspace_id="workspace-a",
    )
    provider = production_orchestrator.provider_manager.resolve_provider("mock")
    calls = 0

    async def execute(_payload):
        nonlocal calls
        calls += 1
        return {"success": True, "response": "should not execute"}

    monkeypatch.setattr(provider, "execute", execute)
    result = await production_orchestrator.runtime.run(
        RuntimeContext(
            request_id="request",
            user_id="principal-a",
            session_id=runtime_session,
            workspace_id=runtime_workspace,
        ),
        task,
        _routing(task),
    )

    assert result.metadata["diagnostic"] == diagnostic
    assert calls == 0


@pytest.mark.asyncio
async def test_completed_mutation_permit_cannot_be_replayed_in_process(
    production_orchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = approved_task(
        task_id="p13-mutation-replay",
        action_type="tool",
        inputs={"title": "P13", "message": "one effect"},
        metadata={
            "tool": "notification",
            "side_effect_class": "non_idempotent_mutation",
        },
        subject_id="principal-a",
        permit_session_id="session-a",
    )
    effects = 0
    notification = production_orchestrator.tool_registry.get_tool("notification")

    def notify(_title: str, _message: str) -> bool:
        nonlocal effects
        effects += 1
        return True

    monkeypatch.setattr(notification, "_notify", notify)
    context = RuntimeContext(
        request_id="execution-a",
        user_id="principal-a",
        session_id="session-a",
    )
    routing = _routing(task)
    first = await production_orchestrator.runtime.run(context, task, routing)
    second = await production_orchestrator.runtime.run(context, task, routing)
    assert first.status.value == "completed"
    assert second.metadata["diagnostic"] == "permit_replayed"
    assert effects == 1


@pytest.mark.parametrize("attack", ["action", "principal", "tamper", "expired"])
def test_approval_resolution_rejects_confused_or_invalid_pending_permit(
    attack: str,
) -> None:
    pending = ExecutionPermit.resolve_pending(
        _task().permit,
        decision=ApprovalDecision.ASK_USER,
    )
    submission = ApprovalSubmission(
        action_id=pending.action_id,
        decision=ApprovalDecision.ALLOW,
    )
    subject = pending.subject_id
    if attack == "action":
        submission = submission.model_copy(update={"action_id": "other-action"})
    elif attack == "principal":
        subject = "principal-b"
    elif attack == "tamper":
        pending = pending.model_copy(update={"target": "tampered-target"})
    else:
        pending = ExecutionPermit.resolve_pending(
            pending,
            decision=ApprovalDecision.ASK_USER,
            now=datetime(2000, 1, 1, tzinfo=timezone.utc),
        )

    with pytest.raises(ValueError):
        ApprovalEngine().resolve(
            pending,
            submission,
            subject_id=subject,
            source="p13-test",
        )
