"""Phase 11.6 — ResponseFormatter continuity: de-roboticizing, duplicate
prevention, natural memory wording, and uncertainty variation.

Parts covered:
    - Part 3: better conversation responses — generic task responses never
      introduce the self or boilerplate (governance/deterministic/approval/
      memory) that the user did not ask about
    - Part 4: duplicate-response prevention — identical consecutive opening
      paragraphs get a deterministic connector
    - Part 5: greeting and closing wording variation via the StyleController
    - Part 7: natural memory wording — recall uses "I remember"-style language
      and never leaks memory ids, visibility rules, allow: labels, UUIDs, or
      retrieval details
    - Part 8: cleaner uncertainty — the deterministic uncertainty lines vary
      by turn while ``turn=None`` keeps every legacy string byte-identical
    - Part 10: formatter purity — formatting never mutates the evaluation and
      is deterministic for any (turn, previous_opening) input
"""

from copy import deepcopy

from app.personality import (
    CANT_DETERMINE_TEXT,
    GREETING_HEY_TEXT,
    THANKS_TEXT,
    UNCERTAIN_MEMORY_TEXT,
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
    PersonalityEvaluation,
    ReasoningPolicy,
    ResponseFormatter,
    SAMAKTHA_IDENTITY_PROFILE,
    TonePolicy,
    VisibleMemory,
    VisibilityType,
)

FORMATTER = ResponseFormatter()

DEFAULT_BEHAVIOR = BehaviorDecision(
    tone=TonePolicy.PROFESSIONAL,
    challenge=ChallengePolicy.NORMAL,
    humor=HumorPolicy.LIGHT,
    reasoning=ReasoningPolicy.MIXED,
    explanation=ExplanationPolicy.NORMAL,
    confidence=ConfidencePolicy.QUALIFIED,
)


def make_evaluation(
    visible: list[VisibleMemory] | None = None,
    greeting: GreetingDecision | None = None,
) -> PersonalityEvaluation:
    return PersonalityEvaluation(
        message="test message",
        identity=IdentityDecision(is_identity_query=False),
        greeting=greeting or GreetingDecision(is_greeting=False),
        profile=SAMAKTHA_IDENTITY_PROFILE,
        behavior=DEFAULT_BEHAVIOR,
        visible_memories=visible or [],
        visibility_summary=None,
        suppressed_count=0,
    )


def recall_memory(content: str, memory_id: str = "mem_1") -> VisibleMemory:
    return VisibleMemory(
        memory_id=memory_id,
        reason="rule 8",
        visibility_type=VisibilityType.ALLOW,
        content=content,
    )


# ---------------------------------------------------------------------------
# Part 3 — no self-introduction or boilerplate in generic responses
# ---------------------------------------------------------------------------


def test_generic_response_never_introduces_self_or_boilerplate() -> None:
    text = FORMATTER.format(
        None,
        "The build finished successfully.",
        conversation_intent=ConversationIntent.UNKNOWN,
    )
    assert text == "The build finished successfully."
    for token in ("governance", "deterministic", "approval", "memory"):
        assert token not in text.lower(), token
    assert "I'm Samaktha" not in text
    assert "I am Samaktha" not in text


def test_boilerplate_words_only_appear_when_relevant() -> None:
    raw = "The task completed. All steps ran without approval needed."
    text = FORMATTER.format(
        None, raw, conversation_intent=ConversationIntent.UNKNOWN
    )
    # The raw provider text is preserved; the formatter never injects extra
    # governance/memory boilerplate of its own.
    assert "task completed" in text
    assert text.count("approval") == 1


# ---------------------------------------------------------------------------
# Part 4 — duplicate-response prevention
# ---------------------------------------------------------------------------


def test_repeated_opening_gets_connector_variation() -> None:
    raw = "Here is the summary of profile.pdf."
    first = FORMATTER.format(
        None,
        raw,
        conversation_intent=ConversationIntent.UNKNOWN,
        turn=1,
        previous_opening=None,
    )
    assert first == raw
    second = FORMATTER.format(
        None,
        raw,
        conversation_intent=ConversationIntent.UNKNOWN,
        turn=2,
        previous_opening=ResponseFormatter.opening_paragraph(raw),
    )
    assert second == "Building on that, " + raw


def test_distinct_openings_are_never_rewritten() -> None:
    raw = "Fresh response content here."
    text = FORMATTER.format(
        None,
        raw,
        conversation_intent=ConversationIntent.UNKNOWN,
        turn=2,
        previous_opening="Something else entirely.",
    )
    assert text == raw


def test_duplicate_prevention_is_opt_in_and_pure() -> None:
    raw = "Same opening paragraph."
    legacy = FORMATTER.format(
        None, raw, conversation_intent=ConversationIntent.UNKNOWN
    )
    assert legacy == raw
    varied = FORMATTER.format(
        None,
        raw,
        conversation_intent=ConversationIntent.UNKNOWN,
        turn=3,
        previous_opening="Same opening paragraph.",
    )
    assert varied == "Adding to that, " + raw


# ---------------------------------------------------------------------------
# Part 5 — greeting and closing variation through the formatter
# ---------------------------------------------------------------------------


def test_greeting_variation_via_formatter() -> None:
    evaluation = make_evaluation(
        greeting=GreetingDecision(is_greeting=True, kind=GreetingKind.HEY)
    )
    assert FORMATTER.format(
        evaluation, "raw", conversation_intent=ConversationIntent.GREETING
    ) == GREETING_HEY_TEXT
    assert FORMATTER.format(
        evaluation,
        "raw",
        conversation_intent=ConversationIntent.GREETING,
        turn=2,
    ) == "Hey, good to see you."


def test_closing_variation_via_formatter() -> None:
    assert FORMATTER.format(
        None, "raw", conversation_intent=ConversationIntent.THANKS
    ) == THANKS_TEXT
    assert FORMATTER.format(
        None,
        "raw",
        conversation_intent=ConversationIntent.THANKS,
        turn=2,
    ) == "Anytime — glad I could help."
    assert FORMATTER.format(
        None,
        "raw",
        conversation_intent=ConversationIntent.GOODBYE,
        turn=2,
    ) == "Goodbye — I'm here whenever you need me."


# ---------------------------------------------------------------------------
# Part 7 — natural memory wording
# ---------------------------------------------------------------------------


def test_memory_recall_uses_natural_wording_and_never_leaks_internals() -> None:
    evaluation = make_evaluation(
        visible=[
            recall_memory("acme project kickoff", "mem_x"),
            recall_memory("acme roadmap is Q3", "mem_y"),
        ]
    )
    text = FORMATTER.format(
        evaluation, "raw", conversation_intent=ConversationIntent.MEMORY_RECALL
    )
    assert text.startswith("Looking back across our recent work")
    for token in (
        "mem_x", "mem_y", "allow", "rule 8", "visibility", "memory_id",
        "uuid", "retrieval", "recall score",
    ):
        assert token not in text.lower(), token


def test_single_memory_recall_is_direct_content() -> None:
    evaluation = make_evaluation(
        visible=[recall_memory("Your favorite IDE is VS Code")]
    )
    assert FORMATTER.format(
        evaluation, "raw", conversation_intent=ConversationIntent.MEMORY_RECALL
    ) == "Your favorite IDE is VS Code"


def test_recall_preamble_rotates_deterministically() -> None:
    evaluation = make_evaluation(
        visible=[recall_memory("acme kickoff"), recall_memory("acme roadmap")]
    )
    t1 = FORMATTER.format(
        evaluation,
        "raw",
        conversation_intent=ConversationIntent.MEMORY_RECALL,
        turn=1,
    )
    t2 = FORMATTER.format(
        evaluation,
        "raw",
        conversation_intent=ConversationIntent.MEMORY_RECALL,
        turn=2,
    )
    assert t1.startswith("Looking back across our recent work")
    assert t2.startswith("Looking back across our recent work")
    assert "mem_" not in t2


# ---------------------------------------------------------------------------
# Part 8 — cleaner uncertainty
# ---------------------------------------------------------------------------


def test_uncertainty_lines_vary_deterministically_by_turn() -> None:
    assert FORMATTER.format(
        None, "", conversation_intent=ConversationIntent.UNKNOWN, turn=1
    ) == CANT_DETERMINE_TEXT
    assert FORMATTER.format(
        None, "", conversation_intent=ConversationIntent.UNKNOWN, turn=2
    ) == "I don't know that yet."
    assert FORMATTER.format(
        None, "", conversation_intent=ConversationIntent.UNKNOWN, turn=3
    ) == "I can't determine that from what I know."
    assert FORMATTER.format(
        None, "", conversation_intent=ConversationIntent.UNKNOWN, turn=4
    ) == "I don't have enough information to answer that."


def test_uncertainty_without_turn_stays_legacy_exact() -> None:
    assert FORMATTER.format(
        None, "", conversation_intent=ConversationIntent.UNKNOWN
    ) == CANT_DETERMINE_TEXT
    assert FORMATTER.format(
        None, "raw", conversation_intent=ConversationIntent.MEMORY_RECALL
    ) == UNCERTAIN_MEMORY_TEXT


def test_memory_uncertainty_variation() -> None:
    evaluation = make_evaluation()
    assert FORMATTER.format(
        evaluation,
        "raw",
        conversation_intent=ConversationIntent.MEMORY_RECALL,
        turn=1,
    ) == UNCERTAIN_MEMORY_TEXT
    assert FORMATTER.format(
        evaluation,
        "raw",
        conversation_intent=ConversationIntent.MEMORY_RECALL,
        turn=3,
    ) == "I don't have enough information to answer that."


# ---------------------------------------------------------------------------
# Part 10 — formatter purity under the new inputs
# ---------------------------------------------------------------------------


def test_format_with_turn_and_previous_opening_never_mutates_evaluation() -> None:
    evaluation = make_evaluation(visible=[recall_memory("acme kickoff", "mem_1")])
    before = deepcopy(evaluation)
    FORMATTER.format(
        evaluation,
        "Here is a result.",
        conversation_intent=ConversationIntent.UNKNOWN,
        turn=3,
        previous_opening="Here is a result.",
    )
    assert evaluation == before


def test_turn_driven_output_is_deterministic() -> None:
    a = FORMATTER.format(
        None,
        "same content",
        conversation_intent=ConversationIntent.UNKNOWN,
        turn=5,
        previous_opening="different",
    )
    b = FORMATTER.format(
        None,
        "same content",
        conversation_intent=ConversationIntent.UNKNOWN,
        turn=5,
        previous_opening="different",
    )
    assert a == b
