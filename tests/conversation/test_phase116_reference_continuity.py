"""Phase 11.6 — conversation continuity: follow-up awareness, topic continuity,
session counters, and natural answer-reference handling.

Parts covered:
    - Part 1: follow-up awareness ("Explain more", "Go deeper", "Tell me more",
      "Can you elaborate?", bare "Why?" / "How?") resolved deterministically
      against the session's short-lived state
    - Part 2: multi-turn topic continuity — "What about GAMBIT?" and
      "How do they work together?" stay intact (never mangled into a single
      stale file reference) and route as natural tasks
    - Part 6: session awareness — conversation_turn, messages_since_last_task,
      messages_since_last_tool, last_goal, last_responses are maintained
      deterministically and never persisted
"""

from app.conversation import (
    ConversationState,
    ReferenceKind,
    ReferenceResolver,
    record_goal,
    record_outputs,
    record_request,
)

RESOLVER = ReferenceResolver()


def _state(**overrides) -> ConversationState:
    base = ConversationState()
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _result(output=None, error=None, metadata=None, routing=None):
    class _Result:
        pass

    result = _Result()
    result.output = output or {}
    result.error = error
    result.metadata = metadata or {}
    result.routing = routing
    return result


# ---------------------------------------------------------------------------
# Part 1 — follow-up awareness
# ---------------------------------------------------------------------------


def test_explain_more_resolves_previous_command_topic() -> None:
    result = RESOLVER.resolve(
        "Explain more", _state(last_command="What is CAP?")
    )
    assert result.resolved is True
    assert result.kind == ReferenceKind.COMMAND
    assert result.request == "Explain more about What is CAP?."


def test_go_deeper_resolves_active_document() -> None:
    result = RESOLVER.resolve(
        "Go deeper",
        _state(active_document="profile.pdf", last_command="Read profile.pdf"),
    )
    assert result.resolved is True
    assert result.kind == ReferenceKind.DOCUMENT
    assert result.request == "Go deeper into profile.pdf."


def test_go_deeper_prefers_active_code_file_over_last_command() -> None:
    result = RESOLVER.resolve(
        "Go deeper",
        _state(active_code_file="src/main.py", last_command="What is GAMBIT?"),
    )
    assert result.kind == ReferenceKind.CODE_FILE
    assert result.request == "Go deeper into src/main.py."


def test_tell_me_more_resolves_last_resource() -> None:
    result = RESOLVER.resolve(
        "Tell me more", _state(last_resource=r"C:\work\project")
    )
    assert result.resolved is True
    assert result.kind == ReferenceKind.RESOURCE
    assert result.request == "Tell me more about C:\\work\\project."


def test_can_you_elaborate_resolves_last_command() -> None:
    result = RESOLVER.resolve(
        "Can you elaborate?", _state(last_command="What is CAP?")
    )
    assert result.request == "Elaborate on What is CAP?."


def test_give_more_details_resolves_active_document() -> None:
    result = RESOLVER.resolve(
        "Give more details", _state(active_document="report.pdf")
    )
    assert result.request == "Give more details about report.pdf."


def test_bare_why_resolves_last_topic() -> None:
    result = RESOLVER.resolve("Why?", _state(last_command="What is CAP?"))
    assert result.resolved is True
    assert result.kind == ReferenceKind.COMMAND
    assert result.request == "Explain What is CAP?."


def test_bare_how_resolves_last_resource() -> None:
    result = RESOLVER.resolve(
        "How so?", _state(active_document="profile.pdf")
    )
    assert result.request == "Explain profile.pdf."


def test_specific_topic_follow_up_is_not_rewritten() -> None:
    result = RESOLVER.resolve(
        "Explain more about GAMBIT", _state(last_command="What is CAP?")
    )
    assert result.resolved is False
    assert result.request == "Explain more about GAMBIT"


def test_elaboration_without_state_is_passthrough() -> None:
    result = RESOLVER.resolve("Explain more", ConversationState())
    assert result.resolved is False
    assert result.request == "Explain more"


def test_elaboration_is_pure_and_never_mutates_state() -> None:
    state = _state(last_command="What is CAP?")
    snapshot = state.model_dump()
    RESOLVER.resolve("Tell me more", state)
    assert state.model_dump() == snapshot


# ---------------------------------------------------------------------------
# Part 2 — multi-turn topic continuity
# ---------------------------------------------------------------------------


def test_topic_continuation_phrases_stay_intact() -> None:
    state = _state(last_command="Explain CAP")
    assert RESOLVER.resolve("What about GAMBIT?", state).resolved is False
    assert RESOLVER.resolve("How do they work together?", state).resolved is False
    assert RESOLVER.resolve("How do they work together?", state).request == (
        "How do they work together?"
    )


def test_three_message_topic_sequence_never_mangles_references() -> None:
    state = _state(last_command="What about GAMBIT?")
    r3 = RESOLVER.resolve("How do they work together?", state)
    assert r3.resolved is False
    assert r3.request == "How do they work together?"


# ---------------------------------------------------------------------------
# Part 6 — session awareness (continue/earlier/answer references)
# ---------------------------------------------------------------------------


def test_continue_from_here_resolves_last_command() -> None:
    result = RESOLVER.resolve(
        "continue from here", _state(last_command="Read profile.pdf")
    )
    assert result.resolved is True
    assert result.request == "continue Read profile.pdf"


def test_pick_up_where_i_left_off_resolves_last_resource() -> None:
    result = RESOLVER.resolve(
        "pick up where I left off", _state(last_resource="C:\\work")
    )
    assert result.resolved is True
    assert result.request == "continue C:\\work"


def test_resume_resolves_last_command() -> None:
    result = RESOLVER.resolve(
        "resume", _state(last_command="install dependencies")
    )
    assert result.resolved is True
    assert result.request == "continue install dependencies"


def test_answer_references_are_never_rewritten() -> None:
    state = _state(
        last_command="Read profile.pdf", active_document="profile.pdf"
    )
    for phrase in (
        "Show me your previous answer",
        "What was your earlier answer?",
        "Repeat your first answer",
        "What was your second answer?",
        "Show your previous response",
    ):
        assert RESOLVER.resolve(phrase, state).resolved is False, phrase


def test_record_request_advances_session_counters() -> None:
    state = ConversationState()
    record_request(state, "hello")
    record_request(state, "what can you do?")
    assert state.conversation_turn == 2
    assert state.messages_since_last_task == 2
    assert state.messages_since_last_tool == 2


def test_record_goal_records_last_goal_and_resets_task_counter() -> None:
    state = ConversationState()
    record_request(state, "Read profile.pdf")
    assert state.messages_since_last_task == 1
    record_goal(state, "read_resource", "profile.pdf")
    assert state.last_goal == "read_resource"
    assert state.messages_since_last_task == 0


def test_record_goal_without_target_still_records_last_goal() -> None:
    state = ConversationState()
    record_request(state, "hello")
    record_goal(state, "answer_question", None)
    assert state.last_goal == "answer_question"
    assert state.messages_since_last_task == 0


def test_record_outputs_with_tool_resets_tool_counter() -> None:
    state = ConversationState()
    record_request(state, "read profile.pdf")
    assert state.messages_since_last_tool == 1
    record_outputs(
        state,
        [
            _result(
                output={"path": "profile.pdf", "result": {"text": "x"}},
                metadata={"tool": "document"},
            )
        ],
    )
    assert state.messages_since_last_tool == 0
    assert state.messages_since_last_task == 1


def test_record_outputs_keeps_capped_response_history() -> None:
    state = ConversationState()
    for i in range(7):
        record_outputs(state, [_result(output={"content": f"answer {i}"})])
    assert state.last_responses == [
        "answer 2", "answer 3", "answer 4", "answer 5", "answer 6",
    ]
    assert len(state.last_responses) == 5


def test_fresh_state_starts_aware_but_empty() -> None:
    state = ConversationState()
    assert state.conversation_turn == 0
    assert state.messages_since_last_task == 0
    assert state.messages_since_last_tool == 0
    assert state.last_goal is None
    assert state.last_responses == []
    assert state.last_opening is None
