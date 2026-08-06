"""Phase 10C — Deterministic Response Formatter acceptance tests.

Verifies the final presentation layer guarantees:
    - identical inputs always produce identical output (the API and the TUI
      therefore always surface the same text)
    - greetings produce a short welcome, never a memory dump
    - identity queries produce the creator answer or a natural capability list
    - memory searches produce a direct recall answer or the uncertainty line
    - deletions produce a confirmation
    - architecture questions produce an honest explanation of the subsystems
    - error paths produce natural user-facing text, never internal wording
    - ``sanitize`` strips every internal identifier (memory ids, UUIDs,
      ``allow:`` labels, subsystem names, CAP/GAMBIT tokens, retrieval
      metadata) from ordinary conversation text
    - the formatter is pure and provider-independent: no storage, no retrieval,
      no LLM calls
"""

from app.personality import (
    ARCHITECTURE_FALLBACK_TEXT,
    CREATOR_IDENTITY_TEXT,
    DENIED_BY_USER_TEXT,
    GREETING_HEY_TEXT,
    MEMORY_DELETED_TEXT,
    SAMAKTHA_IDENTITY_PROFILE,
    SENSITIVE_OUTPUT_TEXT,
    UNCERTAIN_MEMORY_TEXT,
    WHAT_ARE_YOU_TEXT,
    BehaviorDecision,
    ChallengePolicy,
    CollaborationPolicy,
    ConfidencePolicy,
    ConversationIntent,
    ExplanationPolicy,
    GreetingDecision,
    GreetingKind,
    HumorPolicy,
    IdentityDecision,
    IdentityIntent,
    PersonalityEvaluation,
    ReasoningPolicy,
    ResponseFormatter,
    TonePolicy,
    VisibilityType,
    VisibleMemory,
)
from app.personality.models import MemoryVisibilitySummary

DEFAULT_BEHAVIOR = BehaviorDecision(
    tone=TonePolicy.PROFESSIONAL,
    challenge=ChallengePolicy.NORMAL,
    humor=HumorPolicy.LIGHT,
    reasoning=ReasoningPolicy.MIXED,
    explanation=ExplanationPolicy.NORMAL,
    confidence=ConfidencePolicy.QUALIFIED,
)
FORMATTER = ResponseFormatter()


def make_evaluation(
    message: str = "Refactor parser.py",
    *,
    greeting: GreetingDecision | None = None,
    identity: IdentityDecision | None = None,
    visible: list[VisibleMemory] | None = None,
) -> PersonalityEvaluation:
    return PersonalityEvaluation(
        message=message,
        identity=identity or IdentityDecision(is_identity_query=False),
        greeting=greeting or GreetingDecision(is_greeting=False),
        profile=SAMAKTHA_IDENTITY_PROFILE,
        behavior=DEFAULT_BEHAVIOR,
        visible_memories=visible or [],
        visibility_summary=None,
        suppressed_count=0,
    )


# ---------------------------------------------------------------------------
# Greetings: short welcome, never a memory dump
# ---------------------------------------------------------------------------


def test_greeting_is_short_welcome_and_never_a_memory_dump():
    evaluation = make_evaluation(
        message="hi",
        greeting=GreetingDecision(is_greeting=True, kind=GreetingKind.HEY),
        visible=[
            VisibleMemory(
                memory_id="mem_1",
                reason="rule 8",
                visibility_type=VisibilityType.ALLOW,
                content="My favorite IDE is VS Code",
            )
        ],
    )
    text = FORMATTER.format(
        evaluation,
        "Mock provider response",
        conversation_intent=ConversationIntent.GREETING,
    )
    assert text == GREETING_HEY_TEXT
    assert "VS Code" not in text
    assert "mem_1" not in text


def test_greeting_is_localized_by_kind():
    expectations = {
        GreetingKind.GOOD_MORNING: "Good morning! How can I help you today?",
        GreetingKind.GOOD_AFTERNOON: "Good afternoon! How can I help you today?",
        GreetingKind.GOOD_EVENING: "Good evening! How can I help you today?",
        GreetingKind.HOW_ARE_YOU: "I'm doing well, thanks. How can I help you today?",
        GreetingKind.WHATS_UP: "Not much — how can I help you today?",
    }
    for kind, expected in expectations.items():
        evaluation = make_evaluation(
            message="hello",
            greeting=GreetingDecision(is_greeting=True, kind=kind),
        )
        assert FORMATTER.format(
            evaluation, "raw", conversation_intent=ConversationIntent.GREETING
        ) == expected, kind


def test_greeting_without_kind_falls_back_to_hey():
    evaluation = make_evaluation(
        message="hi",
        greeting=GreetingDecision(is_greeting=True),
    )
    assert FORMATTER.format(
        evaluation, "raw", conversation_intent=ConversationIntent.GREETING
    ) == GREETING_HEY_TEXT


# ---------------------------------------------------------------------------
# Identity: creator answer and capability list
# ---------------------------------------------------------------------------


def test_creator_answer_for_who_are_you():
    evaluation = make_evaluation(
        message="who are you?",
        identity=IdentityDecision(
            is_identity_query=True, intent=IdentityIntent.WHO_ARE_YOU
        ),
    )
    text = FORMATTER.format(
        evaluation, "raw", conversation_intent=ConversationIntent.WHO_ARE_YOU
    )
    assert text == CREATOR_IDENTITY_TEXT
    assert "Sreehari R Nair" in CREATOR_IDENTITY_TEXT


def test_creator_answer_for_creator_intent():
    evaluation = make_evaluation(
        message="who made you?",
        identity=IdentityDecision(
            is_identity_query=True, intent=IdentityIntent.WHO_ARE_YOU
        ),
    )
    text = FORMATTER.format(
        evaluation, "raw", conversation_intent=ConversationIntent.CREATOR
    )
    assert text == CREATOR_IDENTITY_TEXT


def test_description_for_what_are_you():
    evaluation = make_evaluation(
        message="what are you?",
        identity=IdentityDecision(
            is_identity_query=True, intent=IdentityIntent.WHAT_ARE_YOU
        ),
    )
    text = FORMATTER.format(
        evaluation, "raw", conversation_intent=ConversationIntent.WHAT_ARE_YOU
    )
    assert text == WHAT_ARE_YOU_TEXT
    assert "Samaktha" in text
    assert "CAP" in text and "GAMBIT" in text


def test_capability_list_for_what_can_you_do():
    evaluation = make_evaluation(
        message="what can you do?",
        identity=IdentityDecision(
            is_identity_query=True, intent=IdentityIntent.WHAT_CAN_YOU_DO
        ),
    )
    text = FORMATTER.format(
        evaluation, "raw", conversation_intent=ConversationIntent.CAPABILITIES
    )
    assert text.startswith("Here's what I can help with:\n")
    for capability in SAMAKTHA_IDENTITY_PROFILE.capabilities:
        assert f"- {capability}" in text


# ---------------------------------------------------------------------------
# Memory recall: direct, never internal metadata
# ---------------------------------------------------------------------------


def test_recall_with_single_memory_returns_content_directly():
    evaluation = make_evaluation(
        message="what is my favorite IDE?",
        visible=[
            VisibleMemory(
                memory_id="mem_1",
                reason="rule 5",
                visibility_type=VisibilityType.ALLOW,
                content="My favorite IDE is VS Code",
            )
        ],
    )
    text = FORMATTER.format(
        evaluation, "raw", conversation_intent=ConversationIntent.MEMORY_RECALL
    )
    assert text == "My favorite IDE is VS Code"
    assert "mem_1" not in text
    assert "allow" not in text.lower()


def test_recall_with_multiple_memories_lists_content_bullets():
    evaluation = make_evaluation(
        message="what do you remember about acme?",
        visible=[
            VisibleMemory(
                memory_id="mem_1",
                reason="rule 5",
                visibility_type=VisibilityType.ALLOW,
                content="acme project kickoff",
            ),
            VisibleMemory(
                memory_id="mem_2",
                reason="rule 8",
                visibility_type=VisibilityType.ALLOW,
                content="acme roadmap is Q3",
            ),
        ],
    )
    text = FORMATTER.format(
        evaluation, "raw", conversation_intent=ConversationIntent.MEMORY_RECALL
    )
    assert text.startswith("Looking back across our recent work")
    assert "acme project kickoff" in text
    assert "acme roadmap is Q3" in text
    assert "mem_1" not in text and "mem_2" not in text


def test_recall_with_no_memories_returns_uncertainty_line():
    evaluation = make_evaluation(message="what is my favorite IDE?")
    text = FORMATTER.format(
        evaluation, "raw", conversation_intent=ConversationIntent.MEMORY_RECALL
    )
    assert text == UNCERTAIN_MEMORY_TEXT


def test_recall_ignores_visible_entries_without_content():
    evaluation = make_evaluation(
        message="what do you remember?",
        visible=[
            VisibleMemory(
                memory_id="mem_1",
                reason="rule 8",
                visibility_type=VisibilityType.ALLOW,
            )
        ],
    )
    text = FORMATTER.format(
        evaluation, "raw", conversation_intent=ConversationIntent.MEMORY_RECALL
    )
    assert text == UNCERTAIN_MEMORY_TEXT


def test_recall_uses_content_not_memory_ids_in_summary_branch():
    evaluation = make_evaluation(
        message="what do you remember?",
        visible=[
            VisibleMemory(
                memory_id="mem_1",
                reason="rule 8",
                visibility_type=VisibilityType.ALLOW,
                content="project status is stable",
            )
        ],
    )
    evaluation.visibility_summary = MemoryVisibilitySummary(
        total_count=1,
        primary_type="project",
        type_counts={"project": 1},
        importance_bucket="high",
        recency_label="recent",
        top_tags=["project"],
        summary_text="1 related project memory",
    )
    text = FORMATTER.format(
        evaluation, "raw", conversation_intent=ConversationIntent.MEMORY_RECALL
    )
    assert text.startswith("Looking back across our recent work")
    assert "project status is stable" in text
    assert "Total:" not in text


# ---------------------------------------------------------------------------
# Deletion confirmation
# ---------------------------------------------------------------------------


def test_deletion_confirmation_overrides_raw_provider_text():
    evaluation = make_evaluation(message="forget my IDE preference")
    report = {
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
    }
    text = FORMATTER.format(
        evaluation,
        "Mock provider response",
        conversation_intent=ConversationIntent.DELETE_MEMORY,
        execution_report=report,
    )
    assert text == MEMORY_DELETED_TEXT


def test_deletion_without_evidence_does_not_claim_removal():
    evaluation = make_evaluation(message="forget my IDE preference")
    text = FORMATTER.format(
        evaluation,
        "Mock provider response",
        conversation_intent=ConversationIntent.DELETE_MEMORY,
    )
    assert text != MEMORY_DELETED_TEXT
    assert "nothing was deleted" in text


# ---------------------------------------------------------------------------
# Architecture questions
# ---------------------------------------------------------------------------


def test_architecture_question_passes_provider_explanation_through():
    evaluation = make_evaluation(message="How do you work?")
    raw = "CAP gates, GAMBIT plans, and I run actions through a runtime."
    assert FORMATTER.format(
        evaluation, raw, conversation_intent=ConversationIntent.ARCHITECTURE
    ) == raw


def test_architecture_question_without_provider_text_uses_fallback():
    evaluation = make_evaluation(message="How are you built?")
    text = FORMATTER.format(
        evaluation, "", conversation_intent=ConversationIntent.ARCHITECTURE
    )
    assert text == ARCHITECTURE_FALLBACK_TEXT
    assert "CAP" in text and "GAMBIT" in text


def test_architecture_question_explains_subsystems():
    evaluation = make_evaluation(message="take me through your internals")
    text = FORMATTER.format(
        evaluation, "", conversation_intent=ConversationIntent.ARCHITECTURE
    )
    for subsystem in ("CAP", "GAMBIT", "workflow", "runtime", "memory"):
        assert subsystem.lower() in text.lower()


# ---------------------------------------------------------------------------
# Sanitize: no internal identifiers in ordinary conversation
# ---------------------------------------------------------------------------


def test_sanitize_strips_every_internal_identifier():
    raw = (
        "Mock provider response with memory_id=678e4965-51ba-4745-8dd5-dbc609ae2538"
        " allow: rule 5 and uuid 22aa4965-51ba-4745-8dd5-dbc609ae0000 and "
        "MemoryController PromptComposer BehaviorDecision retrieval score: 0.83"
    )
    text = FORMATTER.sanitize(raw)
    assert "678e4965-51ba-4745-8dd5-dbc609ae2538" not in text
    assert "22aa4965-51ba-4745-8dd5-dbc609ae0000" not in text
    assert "allow:" not in text.lower()
    assert "MemoryController" not in text
    assert "PromptComposer" not in text
    assert "BehaviorDecision" not in text
    assert "retrieval score" not in text.lower()
    assert "Mock provider response" in text


def test_sanitize_removes_cap_and_gambit_tokens():
    text = FORMATTER.sanitize("CAP blocked and GAMBIT planned it.")
    assert "CAP" not in text
    assert "GAMBIT" not in text


def test_sanitize_replaces_blocked_by_cap_output():
    text = FORMATTER.sanitize("Summary:\n[BLOCKED BY CAP] Output contained critical data.")
    assert text == f"Summary:\n{SENSITIVE_OUTPUT_TEXT}"


def test_sanitize_collapses_whitespace_and_drops_empty_lines():
    text = FORMATTER.sanitize("  hello   world  \n\n   \nsecond   line  ")
    assert text == "hello world\nsecond line"


def test_sanitize_empty_text_is_empty():
    assert FORMATTER.sanitize("") == ""
    assert FORMATTER.sanitize("   ") == ""


def test_ordinary_response_passes_through_without_rewriting_meaning():
    evaluation = make_evaluation(message="list the desktop contents")
    text = FORMATTER.format(evaluation, "Found 3 folders and 2 files.")
    assert text == "Found 3 folders and 2 files."


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_error_with_governance_wording_becomes_denied_message():
    assert FORMATTER.format_error("CAP governance blocked user request") == DENIED_BY_USER_TEXT
    assert FORMATTER.format_error("Governance: denied by policy") == DENIED_BY_USER_TEXT
    assert FORMATTER.format_error("blocked by cap filter") == DENIED_BY_USER_TEXT


def test_error_without_governance_wording_is_sanitized():
    text = FORMATTER.format_error(
        "Provider timeout with memory_id=678e4965-51ba-4745-8dd5-dbc609ae2538"
    )
    assert "678e4965-51ba-4745-8dd5-dbc609ae2538" not in text
    assert "Provider timeout" in text


# ---------------------------------------------------------------------------
# Determinism and interface
# ---------------------------------------------------------------------------


def test_identical_inputs_produce_identical_output():
    evaluation = make_evaluation(message="what do you remember about acme?")
    raw = "Mock provider response"
    first = FORMATTER.format(
        evaluation, raw, conversation_intent=ConversationIntent.MEMORY_RECALL
    )
    second = FORMATTER.format(
        evaluation, raw, conversation_intent=ConversationIntent.MEMORY_RECALL
    )
    assert first == second


def test_accepts_evaluation_as_model_dump_dict():
    evaluation = make_evaluation(
        message="hello",
        greeting=GreetingDecision(is_greeting=True, kind=GreetingKind.HEY),
    )
    dumped = evaluation.model_dump()
    assert FORMATTER.format(
        dumped, "raw", conversation_intent=ConversationIntent.GREETING
    ) == GREETING_HEY_TEXT


def test_accepts_none_evaluation_and_sanitizes():
    text = FORMATTER.format(None, "Mock provider response")
    assert text == "Mock provider response"


def test_unknown_intent_passes_through_sanitized():
    evaluation = make_evaluation(message="what is my favorite IDE?")
    text = FORMATTER.format(evaluation, "Mock provider response")
    assert text == "Mock provider response"
    explicit = FORMATTER.format(
        evaluation, "Mock provider response", conversation_intent=ConversationIntent.UNKNOWN
    )
    assert explicit == "Mock provider response"


def test_accepts_intent_as_raw_string_value():
    evaluation = make_evaluation(
        message="hello",
        greeting=GreetingDecision(is_greeting=True, kind=GreetingKind.HEY),
    )
    assert FORMATTER.format(
        evaluation, "raw", conversation_intent="greeting"
    ) == GREETING_HEY_TEXT


def test_output_is_provider_independent():
    evaluation = make_evaluation(message="hello")
    text = FORMATTER.format(evaluation, "raw").lower()
    for field in ("provider", "model_id", "openai", "anthropic", "claude", "gemini"):
        assert field not in text, field


def test_api_and_tui_surface_identical_text():
    evaluation = make_evaluation(message="hi", greeting=GreetingDecision(is_greeting=True))
    api_text = FORMATTER.format(
        evaluation, "Mock provider response", conversation_intent=ConversationIntent.GREETING
    )
    tui_text = FORMATTER.format(
        evaluation, "Mock provider response", conversation_intent=ConversationIntent.GREETING
    )
    assert api_text == tui_text
    assert api_text == GREETING_HEY_TEXT
