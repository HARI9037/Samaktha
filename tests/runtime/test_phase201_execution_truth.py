from datetime import datetime, timezone

from app.personality import ResponseFormatter
from app.personality.models import ConversationIntent
from app.personality.response_formatter import MEMORY_DELETED_TEXT
from app.runtime.execution_truth import enforce_execution_truth, explain_execution_truth
from app.runtime.report import ExecutionReport, ExecutionTruthState


def _report(state: ExecutionTruthState, *, success: bool = False, tool: bool = False, error: str | None = None) -> ExecutionReport:
    tool_results = [
        {
            "task_id": "tool-1",
            "status": "completed" if success else "failed",
            "output": {"created": "C:/Users/user/Desktop/demo.md"} if success else {},
            "metadata": {"runtime_action_type": "tool", "worker_id": "local-dispatcher"},
        }
    ] if tool else []
    return ExecutionReport(
        plan_id="plan-1",
        success=success,
        execution_state=state,
        executed_tasks=["tool-1"] if success or tool else [],
        tool_results=tool_results,
        errors=[error] if error else [],
        approval_status="approved" if success else "unknown",
        started_at=datetime.now(timezone.utc),
    )


def test_planner_only_flow_cannot_produce_completion_language():
    text = enforce_execution_truth(
        "The file has been created successfully.",
        _report(ExecutionTruthState.PLANNED),
    )
    assert "created successfully" not in text.lower()
    assert "execution plan" in text.lower()


def test_formatter_waits_for_execution_report():
    text = ResponseFormatter().format(
        None,
        "The file has been created successfully.",
        conversation_intent=ConversationIntent.UNKNOWN,
    )
    assert "created successfully" not in text.lower()
    assert "no execution evidence" in text.lower()


def test_approval_blocks_execution_responses():
    report = _report(
        ExecutionTruthState.WAITING_APPROVAL,
        error="approval required: CAP governance requests user confirmation",
    )
    text = enforce_execution_truth("The file has been created.", report)
    assert text.startswith("Approval Required")
    assert "Awaiting approval" in text


def test_runtime_success_produces_completion():
    report = _report(ExecutionTruthState.SUCCEEDED, success=True, tool=True)
    text = enforce_execution_truth("The file has been created successfully.", report)
    assert text == "The file has been created successfully."


def test_runtime_failure_produces_failure():
    report = _report(ExecutionTruthState.FAILED, error="FilesystemTool failed")
    text = enforce_execution_truth("The file has been created successfully.", report)
    assert text.startswith("The runtime reported a failure.")
    assert "FilesystemTool failed" in text


def test_tool_failure_never_reports_success():
    report = _report(ExecutionTruthState.FAILED, tool=True, error="permission denied")
    text = enforce_execution_truth("I created the file.", report)
    assert "created" not in text.lower()
    assert "failure" in text.lower()


def test_succeeded_report_with_only_text_generation_does_not_claim_execution():
    report = ExecutionReport(
        plan_id="plan-1",
        success=True,
        execution_state=ExecutionTruthState.SUCCEEDED,
        executed_tasks=["text-1"],
        provider_results=[{"task_id": "text-1", "status": "completed"}],
        approval_status="approved",
        started_at=datetime.now(timezone.utc),
    )
    text = enforce_execution_truth("I created the file and wrote the config.", report)
    assert "created" not in text.lower()
    assert "cannot claim" in text.lower()


def test_tool_result_that_deleted_nothing_is_not_success():
    report = ExecutionReport(
        plan_id="plan-1",
        success=True,
        execution_state=ExecutionTruthState.SUCCEEDED,
        executed_tasks=["tool-1"],
        tool_results=[
            {
                "task_id": "tool-1",
                "status": "completed",
                "output": {"action": "delete", "deleted": False, "count": 0},
            }
        ],
        approval_status="approved",
        started_at=datetime.now(timezone.utc),
    )
    text = enforce_execution_truth("I removed those preferences.", report)
    assert "removed" not in text.lower()
    assert "cannot claim" in text.lower()


def test_completion_verbs_once_ungated_are_now_gated():
    blind_spots = [
        "I removed the file.",
        "The file was removed.",
        "I have written the file.",
        "I completed the task.",
        "The task was completed.",
        "I deployed the service.",
        "I did it.",
        "The server is running now.",
    ]
    for claim in blind_spots:
        text = enforce_execution_truth(claim, None)
        assert "cannot claim" in text.lower(), f"claim passed ungated: {claim}"


def test_delete_memory_formatter_requires_verified_deletion():
    formatter = ResponseFormatter()
    confirmed = formatter.format(
        None,
        "raw",
        conversation_intent=ConversationIntent.DELETE_MEMORY,
        execution_report={
            "plan_id": "plan-1",
            "success": True,
            "execution_state": "succeeded",
            "tool_results": [
                {
                    "task_id": "tool-1",
                    "status": "completed",
                    "output": {"action": "delete", "deleted": 1, "count": 1},
                }
            ],
        },
    )
    assert confirmed == MEMORY_DELETED_TEXT
    not_confirmed = formatter.format(
        None,
        "raw",
        conversation_intent=ConversationIntent.DELETE_MEMORY,
        execution_report={
            "plan_id": "plan-1",
            "success": True,
            "execution_state": "succeeded",
            "tool_results": [
                {
                    "task_id": "tool-1",
                    "status": "completed",
                    "output": {"action": "delete", "deleted": 0, "count": 0},
                }
            ],
        },
    )
    assert not_confirmed != MEMORY_DELETED_TEXT


def test_execution_truth_states_are_deterministic():
    first = enforce_execution_truth("I deleted the file.", _report(ExecutionTruthState.PLANNED))
    second = enforce_execution_truth("I deleted the file.", _report(ExecutionTruthState.PLANNED))
    assert first == second


def test_explainability_reports_missing_runtime_evidence():
    text = explain_execution_truth(None)
    assert "No execution evidence exists." in text
    assert "planning stage" in text


def test_explainability_reports_runtime_evidence_counts():
    text = explain_execution_truth(_report(ExecutionTruthState.SUCCEEDED, success=True, tool=True))
    assert "Execution state: succeeded" in text
    assert "Executed tasks: 1" in text
    assert "Tool results: 1" in text
