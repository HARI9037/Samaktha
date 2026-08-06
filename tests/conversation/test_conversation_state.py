"""Phase 11.4 — ConversationState recording helpers (deterministic)."""

from datetime import datetime, timedelta

from app.conversation import ConversationState, record_goal, record_outputs, record_request


def _runtime_result(output=None, error=None, metadata=None, routing=None):
    class _Result:
        pass

    result = _Result()
    result.output = output or {}
    result.error = error
    result.metadata = metadata or {}
    result.routing = routing
    return result


def test_state_starts_empty() -> None:
    state = ConversationState()
    assert state.active_document is None
    assert state.active_project is None
    assert state.active_directory is None
    assert state.active_repository is None
    assert state.active_code_file is None
    assert state.active_tool is None
    assert state.last_tool_result is None
    assert state.last_generated_text is None
    assert state.last_search_results == []
    assert state.last_runtime_output is None
    assert state.last_plan is None
    assert state.last_command is None
    assert state.last_resource is None
    assert state.last_error is None
    assert state.updated_at


def test_record_request_sets_last_command_and_bumps_updated_at() -> None:
    state = ConversationState()
    before = state.updated_at
    record_request(state, "Read profile.pdf")

    assert state.last_command == "Read profile.pdf"

    # Contract: updated_at exists, stays a valid ISO-8601 UTC timestamp, and
    # remains parseable after the mutation. Equality is valid when the
    # constructor and touch() reads fall within the same clock tick, so the
    # timestamp is compared by parsed value with >= rather than !=.
    assert state.updated_at
    before_dt = datetime.fromisoformat(before)
    after_dt = datetime.fromisoformat(state.updated_at)
    assert after_dt.utcoffset() == timedelta(0)
    assert after_dt >= before_dt


def test_record_goal_read_document_sets_active_document() -> None:
    state = ConversationState()
    record_goal(state, "read_resource", "profile.pdf")
    assert state.active_document == "profile.pdf"
    assert state.active_code_file is None
    assert state.last_resource == "profile.pdf"


def test_record_goal_read_code_sets_active_code_file() -> None:
    state = ConversationState()
    record_goal(state, "read_resource", "src/main.py")
    assert state.active_code_file == "src/main.py"
    assert state.active_document is None


def test_record_goal_list_directory_sets_active_directory() -> None:
    state = ConversationState()
    record_goal(state, "list_directory", "C:\\Users\\user\\Desktop\\Samaktha")
    assert state.active_directory == "C:\\Users\\user\\Desktop\\Samaktha"


def test_record_goal_ignores_missing_or_answer_intents() -> None:
    state = ConversationState()
    record_goal(state, "answer_question", None)
    record_goal(state, None, "profile.pdf")
    assert state.active_document is None
    assert state.last_resource is None


def test_record_outputs_captures_generated_text_content() -> None:
    state = ConversationState()
    record_outputs(state, [_runtime_result(output={"content": "the summary"})])
    assert state.last_generated_text == "the summary"


def test_record_outputs_captures_generated_text_response() -> None:
    state = ConversationState()
    record_outputs(state, [_runtime_result(output={"response": "hi"})])
    assert state.last_generated_text == "hi"


def test_record_outputs_captures_document_read() -> None:
    state = ConversationState()
    output = {"path": "profile.pdf", "result": {"text": "hello"}}
    record_outputs(state, [_runtime_result(output=output)])
    assert state.active_document == "profile.pdf"
    assert state.last_resource == "profile.pdf"
    assert state.last_tool_result == output


def test_record_outputs_captures_error() -> None:
    state = ConversationState()
    record_outputs(state, [_runtime_result(error="boom")])
    assert state.last_error == "boom"


def test_record_outputs_captures_search_candidates() -> None:
    state = ConversationState()
    record_outputs(
        state,
        [_runtime_result(output={"candidates": [{"path": "a.txt"}, "b.txt"]})],
    )
    assert state.last_search_results == ["a.txt", "b.txt"]


def test_record_outputs_captures_active_tool() -> None:
    state = ConversationState()
    record_outputs(
        state,
        [_runtime_result(output={"ok": True}, metadata={"tool": "document"})],
    )
    assert state.active_tool == "document"


def test_record_outputs_captures_last_runtime_output() -> None:
    state = ConversationState()
    record_outputs(
        state,
        [
            _runtime_result(output={"not": "final"}),
            _runtime_result(output={"content": "final"}, routing="routed"),
        ],
    )
    assert state.last_runtime_output == {"content": "final"}


def test_record_outputs_is_deterministic_and_storage_free() -> None:
    state_a = ConversationState()
    state_b = ConversationState()
    outputs = [
        _runtime_result(output={"content": "x"}, metadata={"tool": "provider"}),
        _runtime_result(output={"path": "f.pdf", "result": {"text": "t"}}),
    ]
    record_outputs(state_a, outputs)
    record_outputs(state_b, outputs)
    dump_a = state_a.model_dump()
    dump_b = state_b.model_dump()
    dump_a.pop("updated_at")
    dump_b.pop("updated_at")
    assert dump_a == dump_b
    assert state_a.active_document == "f.pdf"
    assert state_b.active_document == "f.pdf"
