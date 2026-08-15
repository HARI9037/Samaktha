"""Phase 20.2 — SessionBuilder.

Deterministic session extraction. All metadata and history events are derived
strictly from runtime evidence. This module never guesses, never infers, and
never calls any LLM.

Allowed inputs
--------------
- ExecutionReport
- WorkflowResult
- ApprovalDecision / approval_result
- ToolResult (via ExecutionReport.tool_results)
- RuntimeSummary (plain string)
- ProviderResult (via ExecutionReport.provider_results)

Forbidden
---------
- Regex heuristics over conversation text
- LLM summaries
- Invented milestones, bugs, or files
- Any data not directly sourced from the above runtime artifacts

Phase 20.2.1 hardening
-----------------------
- build_history_entries() now accepts and sets ``turn_number`` via
  ``base_turn_number`` parameter (assigned by SessionManager).
- ``_dedupe_append()`` helper enforces duplicate-free, stable-ordered lists.
- ``update_metadata()`` uses ``_dedupe_append()`` throughout.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from app.memory.session_models import SessionHistoryEntry, SessionMetadata


def _dedupe_append(lst: list[str], value: str) -> None:
    """Append ``value`` to ``lst`` only if not already present.

    Preserves stable insertion order; never duplicates.
    """
    if value and value not in lst:
        lst.append(value)


def _tool_evidence(entry: Any) -> tuple[str | None, str | None, dict[str, Any]]:
    """Normalize tool-result evidence to ``(tool, action, args)``.

    Supports both the flat canonical shape ``{"tool", "action", "args"}`` and
    the runtime shape ``{"metadata": {"tool", "action", "args"}}`` produced by
    the runtime's ToolExecutor. Only documented evidence fields are returned;
    nothing is inferred.
    """
    if isinstance(entry, dict):
        nested = entry.get("metadata")
        if isinstance(nested, dict):
            entry = nested
        tool = entry.get("tool")
        action = entry.get("action")
        args = entry.get("args")
        return tool, action, args if isinstance(args, dict) else {}
    if hasattr(entry, "metadata") and isinstance(entry.metadata, dict):
        return _tool_evidence(entry.metadata)
    return None, None, {}


class SessionBuilder:
    """Deterministic session extraction.

    Derives all metadata and history events strictly from runtime evidence.
    Never guesses, never infers, never uses LLMs.
    """

    @staticmethod
    def build_history_entries(
        user_message: str,
        assistant_response: str,
        execution_report: Any | None = None,
        workflow_result: Any | None = None,
        approval_result: Any | None = None,
        runtime_summary: str | None = None,
        base_turn_number: int = 0,
        logical_id: str | None = None,
        timestamp: str | None = None,
    ) -> list[SessionHistoryEntry]:
        """Convert one conversation turn into two SessionHistoryEntry objects.

        Parameters
        ----------
        base_turn_number:
            The turn number to assign to the *user* entry. The assistant entry
            receives ``base_turn_number + 1``.  SessionManager passes its
            persisted ``next_turn_number`` here so the counter is monotonic
            across cache evictions.
        logical_id:
            Deterministic logical identifier for this interaction.
        timestamp:
            Deterministic timestamp for this interaction.
        """
        # Determine deterministic identity and timestamp
        base_id = logical_id
        now = timestamp
        
        if execution_report is not None:
            if not base_id and hasattr(execution_report, "plan_id"):
                base_id = str(execution_report.plan_id)
            if not now and hasattr(execution_report, "started_at") and execution_report.started_at:
                if hasattr(execution_report.started_at, "isoformat"):
                    now = execution_report.started_at.isoformat()
                else:
                    now = str(execution_report.started_at)
                    
        if not base_id:
            base_id = "unknown_interaction"
            
        if not now:
            now = "1970-01-01T00:00:00+00:00"

        # ---- extract from runtime evidence only ----------------------------
        tool_calls: list[str] = []
        execution_state = "none"
        task_ids: list[str] = []
        approval_state: str | None = None
        provider: str | None = None

        if execution_report is not None:
            if hasattr(execution_report, "executed_tasks"):
                task_ids = list(execution_report.executed_tasks)

            if hasattr(execution_report, "tool_results"):
                seen_tools: set[str] = set()
                for t in execution_report.tool_results:
                    tool_name, _action, _args = _tool_evidence(t)
                    if tool_name and tool_name not in seen_tools:
                        seen_tools.add(tool_name)
                        tool_calls.append(tool_name)

            if hasattr(execution_report, "provider_results"):
                for pr in execution_report.provider_results:
                    if isinstance(pr, dict):
                        pname = pr.get("routing", {}).get("provider_id")
                        if pname:
                            provider = str(pname)
                            break

            if hasattr(execution_report, "execution_state"):
                state = execution_report.execution_state
                execution_state = state.value if hasattr(state, "value") else str(state)

        if approval_result is not None and hasattr(approval_result, "decision"):
            dec = approval_result.decision
            approval_state = dec.value if hasattr(dec, "value") else str(dec)

        # ---- construct entries --------------------------------------------
        user_entry = SessionHistoryEntry(
            id=f"evt_user_{base_id}",
            timestamp=now,
            role="user",
            content=user_message,
            turn_number=base_turn_number,
        )

        assistant_entry = SessionHistoryEntry(
            id=f"evt_assistant_{base_id}_{execution_state}",
            timestamp=now,
            role="assistant",
            content=assistant_response,
            turn_number=base_turn_number + 1,
            execution_state=execution_state,
            approval_state=approval_state,
            task_ids=task_ids,
            tool_calls=tool_calls,
            provider=provider,
            runtime_summary=runtime_summary,
        )

        return [user_entry, assistant_entry]

    @staticmethod
    def update_metadata(
        metadata: SessionMetadata,
        history_entries: list[SessionHistoryEntry],
        execution_report: Any | None = None,
        workflow_result: Any | None = None,
    ) -> SessionMetadata:
        """Deterministically extract lists from execution evidence into SessionMetadata.

        Only data that originates directly from ``execution_report`` or
        ``workflow_result`` is written. Nothing is inferred or invented.
        Duplicate-free lists are maintained via ``_dedupe_append``.
        """
        if execution_report is not None and hasattr(execution_report, "tool_results"):
            for t in execution_report.tool_results:
                tool_name, action, args = _tool_evidence(t)
                if tool_name:
                    _dedupe_append(metadata.tools_used, str(tool_name))

                if tool_name == "filesystem":
                    path = (
                        args.get("path")
                        or args.get("file_path")
                        or args.get("target_path")
                    )
                    if path:
                        path_str = str(path)
                        if action in ("write", "create", "write_to_file"):
                            _dedupe_append(metadata.files_created, path_str)
                        elif action in (
                            "edit", "modify", "replace",
                            "replace_file_content", "multi_replace_file_content",
                        ):
                            _dedupe_append(metadata.files_modified, path_str)
                        elif action == "delete":
                            _dedupe_append(metadata.files_deleted, path_str)

        if execution_report is not None and hasattr(execution_report, "errors"):
            for err in execution_report.errors:
                _dedupe_append(metadata.runtime_errors, str(err))

        # Providers extracted from provider_results
        if execution_report is not None and hasattr(execution_report, "provider_results"):
            for pr in execution_report.provider_results:
                if isinstance(pr, dict):
                    pname = pr.get("routing", {}).get("provider_id")
                    if pname:
                        _dedupe_append(metadata.providers_used, str(pname))

        # Update message count
        metadata.message_count += len(history_entries)
        metadata.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        return metadata
