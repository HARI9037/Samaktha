"""Phase 11.5 — ResponseFormatter hardening regression tests.

Verifies the Phase 11.5 formatter guarantees:
    - the no-hallucination comparison policy: known agents get only curated,
      verified facts; unknown targets get the exact uncertainty line; no target
      resolves to the no-evidence line; nothing is fabricated about external
      systems
    - the uncertainty policy: memory with no verified basis and unanswerable
      requests resolve to the deterministic uncertainty lines
    - consistent formatting: uniform bullets and paragraph breaks, no duplicated
      paragraphs, no empty markdown emphasis (``****``), no stray ``*``, and no
      missing list labels after internal tokens are stripped
    - no leaked internal objects, identifiers, or provider text
    - formatting never mutates the evaluation (no memory writes during render)
"""

from copy import deepcopy

from app.personality import (
    CANT_DETERMINE_TEXT,
    COMPARISON_CLOSING,
    COMPARISON_PREAMBLE,
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
    IntentEngine,
    KNOWN_AGENT_FACTS,
    NO_COMPARISON_EVIDENCE_TEXT,
    PersonalityEvaluation,
    ReasoningPolicy,
    ResponseFormatter,
    SAMAKTHA_IDENTITY_PROFILE,
    TonePolicy,
    UNCERTAIN_MEMORY_TEXT,
    UNKNOWN_AGENT_COMPARISON_TEXT,
    VisibleMemory,
    VisibilityType,
)

FORMATTER = ResponseFormatter()
ENGINE = IntentEngine()

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
# No-hallucination comparison policy (Part 2)
# ---------------------------------------------------------------------------


def test_known_agent_comparison_is_deterministic_and_verified_only():
    text = FORMATTER.format(
        None, "raw", conversation_intent=ConversationIntent.COMPARISON,
        comparison_target="ChatGPT",
    )
    assert text == FORMATTER.format(
        None, "raw", conversation_intent=ConversationIntent.COMPARISON,
        comparison_target="ChatGPT",
    )
    assert COMPARISON_PREAMBLE in text
    assert "ChatGPT is a cloud-hosted conversational AI assistant made by OpenAI." in text
    assert COMPARISON_CLOSING in text
    # Never fabricated claims about the external system.
    for banned in ("faster", "better than", "beats", "more powerful", "100x", "4x", "benchmark"):
        assert banned not in text.lower(), banned


def test_unknown_agent_uses_exact_uncertainty_line():
    text = FORMATTER.format(
        None, "raw", conversation_intent=ConversationIntent.COMPARISON,
        comparison_target="bazbo corp",
    )
    assert text == (
        "I'm Samaktha. Structured comparison\n\n"
        "There is no objective benchmark for bazbo corp.\n\n"
        "Conclusion: the best choice depends on the task and available evidence."
    )


def test_comparison_without_target_uses_no_evidence_line():
    text = FORMATTER.format(
        None, "raw", conversation_intent=ConversationIntent.COMPARISON,
        comparison_target=None,
    )
    assert text == NO_COMPARISON_EVIDENCE_TEXT


def test_no_comparison_ever_fabricates_an_external_claim():
    for target in list(KNOWN_AGENT_FACTS) + ["acme"]:
        text = FORMATTER.format(
            None, "raw", conversation_intent=ConversationIntent.COMPARISON,
            comparison_target=target,
        )
        assert "I'm Samaktha" in text or "enough verified information" in text
        assert "memory_id" not in text
        assert "allow:" not in text.lower()


def test_engine_targets_are_all_in_formatter_registry():
    for phrase, expected in (
        ("compare samaktha to chatgpt", "ChatGPT"),
        ("samaktha vs claude", "Claude"),
        ("are you better than gemini", "Gemini"),
        ("samaktha vs github copilot", "GitHub Copilot"),
    ):
        result = ENGINE.classify_detailed(phrase)
        assert result.comparison_target == expected
        # A known canonical target must have a verified fact in the registry,
        # so the pipeline never falls through to the unknown-agent line for a
        # target the engine itself recognizes.
        assert expected in KNOWN_AGENT_FACTS


# ---------------------------------------------------------------------------
# Uncertainty policy (Part 5)
# ---------------------------------------------------------------------------


def test_memory_recall_without_basis_uses_verified_information_line():
    evaluation = make_evaluation()
    text = FORMATTER.format(
        evaluation, "raw", conversation_intent=ConversationIntent.MEMORY_RECALL
    )
    assert text == UNCERTAIN_MEMORY_TEXT
    assert text == "I don't have enough verified information."


def test_unanswerable_request_with_empty_output_uses_cant_determine_line():
    text = FORMATTER.format(None, "", conversation_intent=ConversationIntent.UNKNOWN)
    assert text == CANT_DETERMINE_TEXT
    text = FORMATTER.format(None, "   ", conversation_intent=ConversationIntent.UNKNOWN)
    assert text == CANT_DETERMINE_TEXT


def test_unanswerable_request_with_content_passes_through_sanitized():
    text = FORMATTER.format(None, "Here is the summary.", conversation_intent=ConversationIntent.UNKNOWN)
    assert text == "Here is the summary."


# ---------------------------------------------------------------------------
# Markdown consistency: no ****, no stray *, no missing labels (Part 3/4)
# ---------------------------------------------------------------------------


def test_sanitize_never_emits_empty_bold_emphasis():
    text = FORMATTER.sanitize("**CAP** and **GAMBIT**")
    assert "*" not in text
    assert "****" not in text
    assert text == "and"


def test_sanitize_repairs_empty_bold_label():
    text = FORMATTER.sanitize("- **CAP:** governance decision")
    assert text == "- governance decision"
    assert "**" not in text


def test_sanitize_repairs_plain_list_labels():
    assert FORMATTER.sanitize("- CAP: approved") == "- approved"
    assert FORMATTER.sanitize("1. : approved") == "1. approved"
    assert FORMATTER.sanitize("- : approved") == "- approved"


def test_sanitize_drops_contentless_list_markers():
    assert FORMATTER.sanitize("Header\n- \n1. \ntrailing") == "Header\ntrailing"


def test_sanitize_leaves_no_stray_asterisks():
    samples = [
        "*MemoryController*",
        "**GAMBIT** process",
        "wrap **CAP** here",
        "a * CAP * b",
    ]
    for sample in samples:
        text = FORMATTER.sanitize(sample)
        assert "*" not in text, (sample, text)


def test_sanitize_preserves_legitimate_text_meaning():
    text = FORMATTER.sanitize("CAP decision approved and work continued")
    assert "decision approved" in text
    assert "CAP" not in text
    assert "*" not in text


def test_consistent_bullets_within_one_response():
    evaluation = make_evaluation(
        visible=[recall_memory("acme kickoff"), recall_memory("acme roadmap")]
    )
    text = FORMATTER.format(
        evaluation, "raw", conversation_intent=ConversationIntent.MEMORY_RECALL
    )
    assert text.startswith("Looking back across our recent work")
    assert "acme kickoff" in text
    assert "acme roadmap" in text


def test_comparison_uses_consistent_paragraph_formatting():
    text = FORMATTER.format(
        None, "raw", conversation_intent=ConversationIntent.COMPARISON,
        comparison_target="Claude",
    )
    paragraphs = text.split("\n\n")
    assert len(paragraphs) == 3
    assert text.count(COMPARISON_PREAMBLE) == 1
    assert text.count("Claude is a cloud-hosted conversational AI assistant") == 1
    assert text.count(COMPARISON_CLOSING) == 1


def test_no_duplicated_paragraphs_in_any_deterministic_output():
    intents = [
        ConversationIntent.GREETING,
        ConversationIntent.WHO_ARE_YOU,
        ConversationIntent.WHAT_ARE_YOU,
        ConversationIntent.CAPABILITIES,
        ConversationIntent.MEMORY_RECALL,
        ConversationIntent.ARCHITECTURE,
        ConversationIntent.VERSION,
        ConversationIntent.THANKS,
        ConversationIntent.GOODBYE,
        ConversationIntent.DELETE_MEMORY,
    ]
    evaluation = make_evaluation(
        greeting=GreetingDecision(is_greeting=True, kind=GreetingKind.HEY)
    )
    for intent in intents:
        text = FORMATTER.format(evaluation, "raw", conversation_intent=intent)
        paragraphs = [p for p in text.split("\n\n") if p.strip()]
        assert len(paragraphs) == len(set(paragraphs)), intent
        assert "****" not in text, intent


# ---------------------------------------------------------------------------
# No leakage of internal objects / identifiers / provider text (Part 4)
# ---------------------------------------------------------------------------


def test_known_comparison_leaks_no_provider_or_internal_text():
    text = FORMATTER.format(
        None, "raw", conversation_intent=ConversationIntent.COMPARISON,
        comparison_target="Gemini",
    ).lower()
    for token in (
        "provider_id", "model_id", "execution_report", "response_model",
        "session_id", "raw_output", "tool_result", "memory_id", "allow:",
        "retrieval", "prompt_composer",
    ):
        assert token not in text, token


def test_deterministic_outputs_never_leak_internal_identifiers():
    evaluation = make_evaluation(visible=[recall_memory("status is stable")])
    outputs = [
        FORMATTER.format(evaluation, "raw", conversation_intent=ConversationIntent.MEMORY_RECALL),
        FORMATTER.format(evaluation, "raw", conversation_intent=ConversationIntent.WHAT_ARE_YOU),
        FORMATTER.format(evaluation, "raw", conversation_intent=ConversationIntent.CAPABILITIES),
    ]
    for text in outputs:
        assert "mem_1" not in text
        assert "allow" not in text.lower()
        assert "rule 8" not in text.lower()


def test_sanitize_strips_new_internal_identifiers():
    raw = (
        "execution_report task_id=9 plan_id=1 workflow_id=2 session_id=s1 "
        "model_id=m1 response_model done raw_output hidden tool_result 42"
    )
    text = FORMATTER.sanitize(raw)
    for token in ("execution_report", "task_id", "plan_id", "workflow_id", "session_id",
                  "model_id", "response_model", "raw_output", "tool_result"):
        assert token not in text, token


# ---------------------------------------------------------------------------
# Purity: formatting never mutates the evaluation (Part 7)
# ---------------------------------------------------------------------------


def test_format_does_not_mutate_evaluation():
    evaluation = make_evaluation(
        visible=[
            recall_memory("project status is stable", "mem_1"),
            recall_memory("acme roadmap is Q3", "mem_2"),
        ]
    )
    before = deepcopy(evaluation)
    FORMATTER.format(evaluation, "raw", conversation_intent=ConversationIntent.MEMORY_RECALL)
    after = deepcopy(evaluation)
    assert after == before


def test_format_does_not_mutate_visible_memories_contents():
    evaluation = make_evaluation(visible=[recall_memory("project status is stable")])
    content_before = evaluation.visible_memories[0].content
    FORMATTER.format(evaluation, "raw", conversation_intent=ConversationIntent.MEMORY_RECALL)
    assert evaluation.visible_memories[0].content == content_before
