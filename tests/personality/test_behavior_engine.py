"""Tests for the deterministic Behavior Engine (Phase 9.3).

Verifies the eight spec acceptance points:
    - serious conversations disable humor
    - technical conversations increase analytical reasoning
    - brainstorming enables mixed reasoning
    - uncertainty selects qualified confidence
    - casual conversations allow light humor
    - challenge policy remains deterministic
    - collaboration defaults to PARTNER
    - behavior decisions are reproducible
plus integration with the PersonalityEngine and freedom from provider/prompt
fields. No randomness, no LLM calls, no prompt generation.
"""

from app.personality import (
    BehaviorDecision,
    BehaviorEngine,
    CapContextView,
    ChallengePolicy,
    CollaborationPolicy,
    ConfidencePolicy,
    ConversationMetadataView,
    ExplanationPolicy,
    HumorPolicy,
    PersonalityEngine,
    ReasoningPolicy,
    TonePolicy,
)


def behavior(message: str, **kwargs) -> BehaviorDecision:
    return BehaviorEngine().evaluate(message, **kwargs)


# ---------------------------------------------------------------------------
# Spec acceptance points
# ---------------------------------------------------------------------------


def test_serious_conversation_disables_humor():
    decision = behavior(
        "URGENT: production is down, we need to restore the database immediately"
    )
    assert decision.tone == TonePolicy.SERIOUS
    assert decision.humor == HumorPolicy.DISABLED


def test_technical_conversation_increases_analytical_reasoning():
    decision = behavior(
        "The /orders API is returning a 500 with this stack trace, can you debug it?"
    )
    assert decision.reasoning == ReasoningPolicy.ANALYTICAL
    assert decision.explanation == ExplanationPolicy.DETAILED


def test_brainstorming_enables_mixed_reasoning():
    decision = behavior("Let's brainstorm some ideas for the onboarding feature")
    assert decision.reasoning == ReasoningPolicy.MIXED
    assert decision.challenge == ChallengePolicy.LIGHT


def test_uncertainty_selects_qualified_confidence():
    decision = behavior("I'm not sure this refactor is safe. What do you think?")
    assert decision.confidence == ConfidencePolicy.QUALIFIED


def test_casual_conversation_allows_light_humor():
    decision = behavior("hey! that's awesome, lol")
    assert decision.tone == TonePolicy.CASUAL
    assert decision.humor in (HumorPolicy.LIGHT, HumorPolicy.PLAYFUL)


def test_collaboration_defaults_to_partner():
    decision = behavior("Summarize what we discussed.")
    assert decision.collaboration == CollaborationPolicy.PARTNER


def test_collaboration_model_default_is_partner():
    decision = BehaviorDecision(
        tone=TonePolicy.PROFESSIONAL,
        challenge=ChallengePolicy.NORMAL,
        humor=HumorPolicy.LIGHT,
        reasoning=ReasoningPolicy.MIXED,
        explanation=ExplanationPolicy.NORMAL,
        confidence=ConfidencePolicy.QUALIFIED,
    )
    assert decision.collaboration == CollaborationPolicy.PARTNER


def test_challenge_policy_remains_deterministic():
    engine = BehaviorEngine()
    messages = (
        "Hi there",
        "Which is better: FastAPI or Flask?",
        "Explain recursion",
        "Let's brainstorm features",
        "What's the plan for the roadmap?",
    )
    for message in messages:
        first = engine.evaluate(message)
        second = engine.evaluate(message)
        assert first.challenge == second.challenge
        assert first == second


def test_behavior_decisions_are_reproducible():
    engine = BehaviorEngine()
    context = CapContextView(workflow_phase="execution")
    metadata = ConversationMetadataView(session_message_count=5)
    first = engine.evaluate(
        "Fix the flaky test for parser.py",
        cap_context=context,
        conversation_metadata=metadata,
    )
    second = engine.evaluate(
        "Fix the flaky test for parser.py",
        cap_context=context,
        conversation_metadata=metadata,
    )
    assert first == second
    assert first.model_dump() == second.model_dump()


# ---------------------------------------------------------------------------
# Per-policy behavior
# ---------------------------------------------------------------------------


def test_identity_question_uses_no_challenge():
    decision = behavior("Who are you?")
    assert decision.challenge == ChallengePolicy.NONE
    assert decision.tone == TonePolicy.PROFESSIONAL


def test_greeting_uses_casual_tone_and_brief_explanation():
    decision = behavior("Hi")
    assert decision.tone == TonePolicy.CASUAL
    assert decision.challenge == ChallengePolicy.NONE
    assert decision.explanation == ExplanationPolicy.BRIEF


def test_first_interaction_is_encouraging():
    decision = BehaviorEngine().evaluate(
        "Let's get started with Samaktha",
        conversation_metadata=ConversationMetadataView(session_message_count=1),
    )
    assert decision.tone == TonePolicy.ENCOURAGING


def test_creative_request_uses_creative_reasoning():
    decision = behavior("Write a poem about our release")
    assert decision.reasoning == ReasoningPolicy.CREATIVE


def test_strategic_request_uses_strategic_reasoning_and_high_challenge():
    decision = behavior("Let's define a roadmap with milestones and next steps")
    assert decision.reasoning == ReasoningPolicy.STRATEGIC
    assert decision.challenge == ChallengePolicy.HIGH


def test_decision_question_challenges_hard():
    decision = behavior("Should I switch the database to PostgreSQL?")
    assert decision.challenge == ChallengePolicy.HIGH


def test_brief_request_shortens_explanation_and_skips_challenge():
    decision = behavior("Briefly, what changed in this diff?")
    assert decision.explanation == ExplanationPolicy.BRIEF
    assert decision.challenge == ChallengePolicy.NONE


def test_direct_command_shifts_to_assist():
    decision = behavior("Please fix the bug in parser.py")
    assert decision.collaboration == CollaborationPolicy.ASSIST
    assert decision.reasoning == ReasoningPolicy.ANALYTICAL


def test_command_during_brainstorm_stays_partner():
    decision = behavior("Come up with ideas, then implement the best one")
    assert decision.collaboration == CollaborationPolicy.PARTNER


# ---------------------------------------------------------------------------
# CAP context influence
# ---------------------------------------------------------------------------


def test_cap_governance_creates_serious_explicit_uncertainty():
    decision = BehaviorEngine().evaluate(
        "Can I get approval to delete the database?",
        cap_context=CapContextView(requires_approval=True, high_risk=True),
    )
    assert decision.tone == TonePolicy.SERIOUS
    assert decision.humor == HumorPolicy.DISABLED
    assert decision.confidence == ConfidencePolicy.EXPLICIT_UNCERTAINTY


def test_cap_workflow_phase_affects_reasoning():
    decision = BehaviorEngine().evaluate(
        "Continue the current task",
        cap_context=CapContextView(workflow_phase="execution"),
    )
    assert decision.reasoning == ReasoningPolicy.ANALYTICAL


def test_future_prediction_is_explicitly_uncertain():
    decision = behavior("Will the new cache improve latency next month?")
    assert decision.confidence == ConfidencePolicy.EXPLICIT_UNCERTAINTY


def test_memory_recall_uses_mixed_reasoning():
    decision = BehaviorEngine().evaluate(
        "Recap this session",
        cap_context=CapContextView(is_memory_recall=True),
    )
    assert decision.reasoning == ReasoningPolicy.MIXED


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------


def test_extract_features_deterministic():
    from app.personality import extract_features

    first = extract_features(
        message="Let's brainstorm some ideas",
        cap_context=CapContextView(workflow_phase="planning"),
    )
    second = extract_features(
        message="Let's brainstorm some ideas",
        cap_context=CapContextView(workflow_phase="planning"),
    )
    assert first == second
    assert first.brainstorming
    assert first.word_count == 5


# ---------------------------------------------------------------------------
# PersonalityEngine integration + freedom from provider/prompt fields
# ---------------------------------------------------------------------------


def test_personality_engine_produces_behavior():
    result = PersonalityEngine().evaluate("Hi")
    assert isinstance(result.behavior, BehaviorDecision)
    assert result.behavior.collaboration == CollaborationPolicy.PARTNER


def test_personality_engine_behavior_with_context():
    result = PersonalityEngine().evaluate(
        "Let's brainstorm onboarding ideas",
        cap_context=CapContextView(workflow_phase="planning"),
        conversation_metadata=ConversationMetadataView(session_message_count=3),
    )
    assert result.behavior.reasoning == ReasoningPolicy.MIXED


def test_behavior_has_no_provider_or_prompt_fields():
    decision = behavior("What do you know about me?")
    flat = str(decision.model_dump()).lower()
    for field in ("provider", "model_id", "prompt", "response"):
        assert field not in flat, field


def test_personality_evaluation_still_free_of_provider_fields():
    result = PersonalityEngine().evaluate("Who are you?")
    flat = str(result.model_dump()).lower()
    for field in ("provider", "model_id", "prompt", "response"):
        assert field not in flat, field
