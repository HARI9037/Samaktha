"""Phase 11.4 — deterministic state-observation helpers.

These are pure functions over a ``ConversationState``: they record what the
user last worked on (request, goal target) and what the runtime produced
(provider text, tool output, search candidates, errors). They never read or
write storage, never learn, and never influence CAP/GAMBIT/Runtime/Provider.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.conversation.models import MAX_LAST_RESPONSES, ConversationState

_CODE_EXTENSIONS = frozenset({
    ".py", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go",
    ".rs", ".java", ".kt", ".kts", ".c", ".cpp", ".h", ".hpp", ".cs", ".rb",
    ".php", ".swift", ".scala", ".sh", ".bash", ".zsh", ".ps1", ".bat",
    ".cmd", ".lua", ".r", ".dart", ".ex", ".exs", ".pl", ".pm", ".jl",
})


def _is_code_file(path: str) -> bool:
    return Path(path).suffix.lower() in _CODE_EXTENSIONS


def _candidate_path(candidate: Any) -> str:
    """Extract a path string from a search candidate of any shape."""
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, dict):
        path = candidate.get("path") or candidate.get("name") or candidate.get("target")
        if path:
            return str(path)
    path = getattr(candidate, "path", None) or getattr(candidate, "name", None)
    return str(path) if path else str(candidate)


def record_request(state: ConversationState, request: str) -> ConversationState:
    """Record the user's most recent request and advance the session counters.

    Every user message advances ``conversation_turn`` and the "messages since
    last task/tool" counters; a later task goal or tool output resets the
    matching counter. This is what makes "Continue", "Earlier", and the
    answer-reference phrases deterministically session-aware.
    """
    state.last_command = request
    state.conversation_turn += 1
    state.messages_since_last_task += 1
    state.messages_since_last_tool += 1
    state.touch()
    return state


def record_goal(
    state: ConversationState,
    intent_value: str | None,
    target_path: str | None,
) -> ConversationState:
    """Record active resources and the last goal parsed from a request."""
    if not intent_value:
        return state
    state.last_goal = intent_value
    state.messages_since_last_task = 0
    if not target_path:
        state.touch()
        return state
    if intent_value == "read_resource":
        if _is_code_file(target_path):
            state.active_code_file = target_path
            state.active_document = None
        else:
            state.active_document = target_path
            state.active_code_file = None
        state.last_resource = target_path
    elif intent_value == "list_directory":
        if target_path != ".":
            state.active_directory = target_path
        state.last_resource = target_path
    elif intent_value in {
        "search_resource",
        "write_resource",
        "delete_resource",
        "move_resource",
        "copy_resource",
        "rename_resource",
    }:
        state.last_resource = target_path
    state.touch()
    return state


def _record_response(state: ConversationState, content: str) -> None:
    """Keep a capped, in-memory history of the latest assistant responses."""
    state.last_responses.append(content)
    if len(state.last_responses) > MAX_LAST_RESPONSES:
        del state.last_responses[: len(state.last_responses) - MAX_LAST_RESPONSES]


def record_outputs(
    state: ConversationState,
    outputs: list[Any] | None,
) -> ConversationState:
    """Record runtime outputs into the session's short-lived working memory."""
    last_runtime_output: dict[str, Any] | None = None
    tool_ran = False
    for output in outputs or []:
        data = getattr(output, "output", None)
        error = getattr(output, "error", None)
        metadata = getattr(output, "metadata", None) or {}
        if error:
            state.last_error = error
        if not isinstance(data, dict):
            continue

        content = data.get("content")
        response = data.get("response")
        if isinstance(content, str) and content.strip():
            state.last_generated_text = content
            _record_response(state, content)
        elif isinstance(response, str) and response.strip():
            state.last_generated_text = response
            _record_response(state, response)

        path = data.get("path")
        if isinstance(path, str) and path:
            state.last_resource = path
            tool_ran = True
            if _is_code_file(path):
                state.active_code_file = path
            else:
                state.active_document = path

        result = data.get("result")
        if isinstance(result, dict):
            state.last_tool_result = data

        candidates = data.get("candidates")
        if isinstance(candidates, list) and candidates:
            state.last_search_results = [_candidate_path(c) for c in candidates]

        internet_results = data.get("results") if data.get("internet") is True else None
        if isinstance(internet_results, list) and internet_results:
            state.last_search_results = [
                str(item.get("url") or item.get("title"))
                for item in internet_results[:10]
                if isinstance(item, dict) and (item.get("url") or item.get("title"))
            ]
            # Extract and store entities for follow-up resolution
            from app.internet.entity_extractor import (
                extract_entities_from_snippets,
                infer_domain_hint,
                infer_format_intent,
                infer_requested_count,
            )
            # Use the original user request to infer intent
            original_request = state.last_command or ""
            domain_hint = infer_domain_hint(original_request)
            format_intent = infer_format_intent(original_request)
            requested_count = infer_requested_count(original_request)
            
            entities = extract_entities_from_snippets(
                internet_results,
                max_entities=requested_count,
                domain_hint=domain_hint,
                format_intent=format_intent,
            )
            state.last_search_entities = entities
            state.last_search_format_intent = format_intent
            state.last_search_domain_hint = domain_hint
            state.last_search_requested_count = requested_count
            
            state.last_tool_result = data
            tool_ran = True

        memory_evidence = data.get("memory_evidence")
        if isinstance(memory_evidence, dict):
            records = memory_evidence.get("records")
            if isinstance(records, list):
                state.last_memory_result_ids = [
                    str(record.get("memory_id"))
                    for record in records
                    if isinstance(record, dict) and record.get("memory_id")
                ]
            else:
                state.last_memory_result_ids = []
            recalled_session = memory_evidence.get("session_id")
            state.last_memory_session_ids = (
                [str(recalled_session)] if recalled_session else []
            )
            state.last_memory_query = str(memory_evidence.get("query") or "")
            state.last_memory_scope = str(
                memory_evidence.get("workspace_id")
                or memory_evidence.get("profile_id")
                or memory_evidence.get("principal_id")
                or ""
            )
            state.last_memory_intent = str(memory_evidence.get("intent") or "")
            state.last_tool_result = data
            tool_ran = True

        tool = metadata.get("tool")
        if isinstance(tool, str) and tool:
            state.active_tool = tool
            tool_ran = True

        if getattr(output, "routing", None) is not None:
            last_runtime_output = data

    if last_runtime_output is not None:
        state.last_runtime_output = last_runtime_output
    if tool_ran:
        state.messages_since_last_tool = 0
    state.touch()
    return state
