import os
import pytest

# Allow multi-instance in tests to avoid single-instance guard interference
os.environ["SAMAKTHA_TEST_ALLOW_MULTI_INSTANCE"] = "1"

from app.core.contracts.policy import (
    ApprovalDecision,
    ActionRisk,
    ExecutionConstraints,
    ExecutionPermit,
    PlannedAction,
    PolicyDecision,
    PrivacyCategory,
    PrivacyClassification,
    authorization_payload,
    authorization_target,
)
from app.core.contracts.runtime import ApprovedRuntimeTask


def approved_task(task_id: str = "test", action_type: str = "text_generation", **kwargs) -> ApprovedRuntimeTask:
    subject_id = kwargs.pop("subject_id", "request-1")
    session_id = kwargs.pop("permit_session_id", None)
    workspace_id = kwargs.pop("permit_workspace_id", None)
    task = ApprovedRuntimeTask(task_id=task_id, title=kwargs.pop("title", "Test"), description=kwargs.pop("description", "Test task"), action_type=action_type, **kwargs)
    operation = PlannedAction(
        action_id=task_id,
        action_type=action_type,
        description=task.description,
        target=authorization_target(action_type, task.metadata.get("tool")),
        payload=authorization_payload(action_type, task.inputs),
    )
    task.permit = ExecutionPermit.issue(
        action=operation,
        subject_id=subject_id,
        session_id=session_id,
        workspace_id=workspace_id,
        policy=PolicyDecision(
            action_id=task_id,
            allowed=True,
            risk=ActionRisk.LOW,
            privacy=PrivacyClassification(category=PrivacyCategory.PUBLIC),
            required_permissions=[],
            approval_required=False,
            use_local_model=False,
            reasons=["test fixture authorization"],
            constraints=ExecutionConstraints(),
        ),
        decision=ApprovalDecision.ALLOW,
        approval_source="test.fixture",
        approval_provenance={"test": True},
    )
    task.metadata.setdefault(
        "required_permissions",
        [scope.value for scope in task.permit.required_permissions],
    )
    task.metadata.setdefault(
        "execution_constraints",
        task.permit.constraints.model_dump(),
    )
    return task
