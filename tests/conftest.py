import pytest

from app.core.contracts.policy import ApprovalDecision, ExecutionPermit
from app.core.contracts.runtime import ApprovedRuntimeTask


def approved_task(task_id: str = "test", action_type: str = "text_generation", **kwargs) -> ApprovedRuntimeTask:
    task = ApprovedRuntimeTask(task_id=task_id, title=kwargs.pop("title", "Test"), description=kwargs.pop("description", "Test task"), action_type=action_type, **kwargs)
    task.permit = ExecutionPermit(action_id=task_id, decision=ApprovalDecision.ALLOW)
    return task
