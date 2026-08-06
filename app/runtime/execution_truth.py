from __future__ import annotations

import re
from typing import Any

from app.runtime.report import ExecutionReport, ExecutionTruthState

_COMPLETION_VERBS = (
    r"(?:created|deleted|removed|modified|updated|installed|sent|pushed|"
    r"committed|executed|wrote|written|saved|moved|copied|completed|deployed|done)"
)
_COMPLETION_RE = re.compile(
    rf"\b(?:I|We)\s*(?:'ve\s+|have\s+|just\s+)*{_COMPLETION_VERBS}\b"
    rf"|\b(?:has|have|was|were)\s+been\s+{_COMPLETION_VERBS}\b"
    rf"|\b(?:was|were)\s+{_COMPLETION_VERBS}\b"
    rf"|\b(?:the\s+)?task\s+(?:completed|finished)\s+successfully\b"
    rf"|\b(?:did\s+it|is\s+(?:now\s+)?(?:running|deployed)|is\s+done)\b",
    re.IGNORECASE,
)


def enforce_execution_truth(text: str, report: ExecutionReport | dict[str, Any] | None) -> str:
    """Gate user-facing completion language on runtime execution evidence."""
    if not text or not _COMPLETION_RE.search(text):
        return text
    parsed = _coerce_report(report)
    if parsed is None:
        return "I have prepared a plan. No execution evidence exists yet, so I cannot claim the action completed."
    if parsed.execution_state == ExecutionTruthState.WAITING_APPROVAL:
        return _approval_required(parsed)
    if parsed.execution_state == ExecutionTruthState.EXECUTING:
        return "I'm executing the approved task."
    if parsed.execution_state == ExecutionTruthState.FAILED:
        return _failure(parsed)
    if parsed.execution_state == ExecutionTruthState.CANCELLED:
        return "The task was cancelled."
    if parsed.execution_state in {ExecutionTruthState.NOT_STARTED, ExecutionTruthState.PLANNED, ExecutionTruthState.APPROVED}:
        return "I have prepared the execution plan. No runtime completion evidence exists yet."
    if parsed.execution_state == ExecutionTruthState.SUCCEEDED and _has_runtime_success(parsed):
        return text
    return "The runtime has not reported a completed action, so I cannot claim it succeeded."


def explain_execution_truth(report: ExecutionReport | dict[str, Any] | None) -> str:
    parsed = _coerce_report(report)
    if parsed is None:
        return "No execution evidence exists.\nThe action remained in the planning stage."
    return "\n".join(
        (
            f"Execution state: {parsed.execution_state.value}",
            f"Executed tasks: {len(parsed.executed_tasks)}",
            f"Tool results: {len(parsed.tool_results)}",
            f"Provider results: {len(parsed.provider_results)}",
            f"Approval status: {parsed.approval_status}",
        )
    )


def _coerce_report(report: ExecutionReport | dict[str, Any] | None) -> ExecutionReport | None:
    if report is None:
        return None
    if isinstance(report, ExecutionReport):
        return report
    if isinstance(report, dict):
        try:
            return ExecutionReport.model_validate(report)
        except Exception:
            return None
    return None


def _has_runtime_success(report: ExecutionReport) -> bool:
    if not report.success:
        return False
    completed_tools = [
        result for result in report.tool_results
        if isinstance(result, dict) and result.get("status") == "completed"
    ]
    return any(_tool_result_has_effect(result) for result in completed_tools)


def _tool_result_has_effect(result: dict) -> bool:
    """A completed tool result counts as evidence only when it mutated state.

    Provider/text-generation results never count as side-effect evidence, and
    a tool that reported an explicit no-op (deleted 0, written 0, count 0)
    does not verify a completion claim either.
    """
    output = result.get("output")
    if not isinstance(output, dict):
        return True
    deleted = output.get("deleted")
    if isinstance(deleted, bool):
        return deleted
    if isinstance(deleted, (int, float)):
        return deleted > 0
    written = output.get("written")
    if isinstance(written, bool):
        return written
    if isinstance(output.get("written_bytes"), (int, float)):
        return output["written_bytes"] > 0
    count = output.get("count")
    if isinstance(count, (int, float)):
        return count > 0
    return True


def _approval_required(report: ExecutionReport) -> str:
    reason = "; ".join(report.errors) if report.errors else "CAP requires approval before execution."
    return "\n".join(
        (
            "Approval Required",
            f"Reason: {reason}",
            f"Requested action: {report.plan_id}",
            "Risk: execution changes are blocked until approval is granted.",
            "Awaiting approval.",
        )
    )


def _failure(report: ExecutionReport) -> str:
    reason = "; ".join(report.errors) if report.errors else "Runtime reported a failure."
    return f"The runtime reported a failure.\nReason: {reason}"
