from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.cap.approval_engine import ApprovalRequest
from app.core.contracts import ApprovedRuntimeTask, RoutingDecision, RuntimeContext
from app.core.contracts.planning import TaskStatus
from app.core.contracts.policy import PlannedAction, authorization_payload
from app.runtime.execution_truth import enforce_execution_truth
from app.runtime.governance import enforce_cap_permit
from app.runtime.report import ExecutionReport, ExecutionTruthState
from app.tui.renderer import _approval_summary_lines


def _report(state: ExecutionTruthState, **updates) -> ExecutionReport:
    values = {
        "plan_id": "pilot-plan",
        "success": state == ExecutionTruthState.SUCCEEDED,
        "execution_state": state,
    }
    values.update(updates)
    return ExecutionReport(**values)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (ExecutionTruthState.WAITING_APPROVAL, "Approval Required"),
        (ExecutionTruthState.DENIED, "denied"),
        (ExecutionTruthState.CANCELLED, "cancelled"),
        (ExecutionTruthState.TIMED_OUT, "timed out"),
        (ExecutionTruthState.FAILED, "failure"),
    ],
)
def test_user_facing_failure_states_never_become_success(state, expected) -> None:
    text = enforce_execution_truth("I completed the action.", _report(state))
    assert expected.lower() in text.lower()
    assert text != "I completed the action."


def test_provider_prose_and_simulation_are_not_side_effect_evidence() -> None:
    assert "cannot claim" in enforce_execution_truth(
        "I sent the message.", None
    ).lower()
    simulated = _report(
        ExecutionTruthState.SUCCEEDED,
        tool_results=[
            {
                "status": "completed",
                "metadata": {"tool": "email", "action": "send"},
                "output": {
                    "status": "simulated",
                    "externally_delivered": False,
                },
            }
        ],
    )
    assert enforce_execution_truth("I sent the email.", simulated) != "I sent the email."


def test_actual_runtime_tool_evidence_allows_truthful_completion() -> None:
    completed = _report(
        ExecutionTruthState.SUCCEEDED,
        tool_results=[
            {
                "status": "completed",
                "metadata": {"tool": "filesystem", "action": "write"},
                "output": {"written_bytes": 12},
            }
        ],
    )
    assert enforce_execution_truth("I wrote the file.", completed) == "I wrote the file."


@pytest.mark.asyncio
async def test_approval_exposes_exact_action_target_arguments_and_risk(
    pilot_orchestrator,
) -> None:
    inputs = {
        "action": "run",
        "executable": "git.exe",
        "args": ["status", "--short"],
        "password": "P14-APPROVAL-SECRET",
    }
    action = PlannedAction(
        action_id="approval-pilot",
        action_type="run",
        description="Run a safe status command",
        target="tool:shell",
        payload=authorization_payload("tool", inputs),
    )
    policy = pilot_orchestrator._policy_engine.evaluate(action)
    permit = await pilot_orchestrator._approval_engine.authorize(
        ApprovalRequest(action=action, operation=action, policy=policy),
        subject_id="pilot-user",
        session_id="pilot-session",
        workspace_id="pilot-workspace",
    )
    task = ApprovedRuntimeTask(
        task_id="approval-pilot",
        title="Git status",
        description=action.description,
        action_type="run",
        inputs=inputs,
        metadata={"tool": "shell"},
        permit=permit,
    )
    result = enforce_cap_permit(
        task,
        RoutingDecision(provider_id="", model_id="", reasoning_summary="tool"),
        started_at=datetime.now(timezone.utc),
        duration_ms=0,
        context=RuntimeContext(
            request_id="approval-pilot",
            user_id="pilot-user",
            session_id="pilot-session",
            workspace_id="pilot-workspace",
        ),
    )

    assert result is not None
    assert result.status == TaskStatus.PAUSED
    assert result.pause is not None
    metadata = result.pause.metadata
    assert metadata["action"] == "run"
    assert metadata["target"] == "tool:shell"
    assert metadata["args"]["executable"] == "git.exe"
    assert metadata["args"]["args"] == ["status", "--short"]
    assert "password" not in metadata["args"]
    assert metadata["risk"] == "critical"
    assert metadata["permissions"] == ["execute"]

    lines = "\n".join(
        _approval_summary_lines(
            {"reason": result.pause.reason, "metadata": metadata}
        )
    )
    assert "Action: run" in lines
    assert "Target: tool:shell" in lines
    assert "git.exe" in lines
    assert "Allow executes only this exact bound operation" in lines
    assert "P14-APPROVAL-SECRET" not in lines
