"""Tests for the deterministic Reflection Engine (Phase 9.5).

Verifies the eleven spec acceptance points:
    - identical conversations produce identical reports
    - technical conversations classified correctly
    - planning conversations detected
    - coding conversations detected
    - clarification requests detected
    - uncertainty captured
    - memory usage reported
    - approval flags reflected
    - no storage access
    - no learning performed
    - no memory updates
plus conversation-type coverage, completion status, descriptive (never
prescriptive) summaries, and integration with the PersonalityEngine and
PromptComposer. No randomness, no LLM, no storage, no side effects.
"""

import inspect

from app.personality import (
    SAMAKTHA_IDENTITY_PROFILE,
    BehaviorDecision,
    CapContextView,
    ChallengePolicy,
    CollaborationPolicy,
    CompletionStatus,
    ConfidencePolicy,
    ConversationMetadataView,
    ConversationType,
    ExplanationPolicy,
    GreetingDecision,
    HumorPolicy,
    IdentityDecision,
    MemoryUsage,
    PersonalityEngine,
    PersonalityEvaluation,
    PromptComposer,
    ReasoningPolicy,
    ReflectionEngine,
    ReflectionReport,
    RiskLevel,
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


def make_evaluation(
    message: str = "Refactor parser.py",
    *,
    behavior: BehaviorDecision = DEFAULT_BEHAVIOR,
    visible: list[VisibleMemory] | None = None,
    summary: MemoryVisibilitySummary | None = None,
    greeting: bool = False,
    identity: bool = False,
) -> PersonalityEvaluation:
    return PersonalityEvaluation(
        message=message,
        identity=IdentityDecision(is_identity_query=identity),
        greeting=GreetingDecision(is_greeting=greeting),
        profile=SAMAKTHA_IDENTITY_PROFILE,
        behavior=behavior,
        visible_memories=visible or [],
        visibility_summary=summary,
    )


def reflect(
    message: str,
    response: str,
    *,
    evaluation: PersonalityEvaluation | None = None,
    cap_context: CapContextView | None = None,
    prompt_composition=None,
) -> ReflectionReport:
    return ReflectionEngine().reflect(
        message,
        response,
        evaluation=evaluation,
        cap_context=cap_context,
        prompt_composition=prompt_composition,
    )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_identical_conversations_produce_identical_reports():
    context = CapContextView(workflow_phase="execution", requires_approval=True)
    engine = ReflectionEngine()
    first = engine.reflect(
        "Why is the API returning a 500?",
        "That usually means an unhandled exception.",
        cap_context=context,
    )
    second = engine.reflect(
        "Why is the API returning a 500?",
        "That usually means an unhandled exception.",
        cap_context=context,
    )
    assert first == second
    assert first.model_dump() == second.model_dump()
    assert first.interaction_summary == second.interaction_summary


def test_identical_conversations_across_engine_instances():
    args = ("Fix the flaky test", "The test now passes deterministically.")
    first = ReflectionEngine().reflect(*args)
    second = ReflectionEngine().reflect(*args)
    assert first == second


# ---------------------------------------------------------------------------
# Conversation classification
# ---------------------------------------------------------------------------


def test_technical_conversation_classified_correctly():
    report = reflect(
        "The API is returning a 500 error with a stack trace, can you debug it?",
        "The traceback points to an unhandled exception in the request handler.",
    )
    assert report.conversation_type == ConversationType.TECHNICAL
    assert report.technical_topic is True


def test_planning_conversation_detected():
    report = reflect(
        "Let's define a roadmap with milestones and next steps for the migration",
        "Here is a proposed plan with three phases.",
    )
    assert report.conversation_type == ConversationType.PLANNING
    assert report.contains_plan is True
    assert report.user_goal_detected is True


def test_coding_conversation_detected_with_code():
    message = "def add(a, b):\n    return a + b\n\nHow do I test this function?"
    report = reflect(message, "Use pytest with a parametrized test.")
    assert report.conversation_type == ConversationType.CODING
    assert report.contains_code is True


def test_coding_conversation_detected_by_intent():
    report = reflect(
        "Implement a function that sorts a list",
        "Here is a merge sort implementation.",
    )
    assert report.conversation_type == ConversationType.CODING
    assert report.user_goal_detected is True


def test_clarification_request_detected():
    report = reflect(
        "What is the best approach here?",
        "Could you clarify what you mean by 'best'?",
    )
    assert report.clarification_requested is True
    assert report.conversation_type == ConversationType.CLARIFICATION


def test_greeting_classified_from_evaluation():
    report = reflect("Hi", "Hello!", evaluation=make_evaluation(greeting=True))
    assert report.conversation_type == ConversationType.GREETING
    assert report.user_goal_detected is False


def test_identity_classified_from_evaluation():
    report = reflect(
        "Who are you?",
        "I am Samaktha.",
        evaluation=make_evaluation(identity=True),
    )
    assert report.conversation_type == ConversationType.IDENTITY


def test_creative_classified_correctly():
    report = reflect("Write a poem about the sea", "The sea is wide and deep.")
    assert report.conversation_type == ConversationType.CREATIVE
    assert report.creative_topic is True


def test_general_conversation_falls_back_to_general():
    report = reflect("Tell me about the weather", "It is sunny today.")
    assert report.conversation_type == ConversationType.GENERAL


def test_contains_questions_detected():
    report = reflect("What is a lambda in Python?", "A lambda is an anonymous function.")
    assert report.contains_questions is True


# ---------------------------------------------------------------------------
# Uncertainty, behavior, response metrics
# ---------------------------------------------------------------------------


def test_user_uncertainty_captured():
    report = reflect(
        "I'm not sure if this refactor is safe. What do you think?",
        "The refactor looks reasonable with a couple of risk areas.",
    )
    assert report.uncertainty_detected is True


def test_response_hedging_captured():
    report = reflect(
        "Will the new cache improve latency?",
        "I'm not certain, but it could help in most cases.",
    )
    assert report.uncertainty_detected is True


def test_behavior_and_reasoning_reported_from_decision():
    behavior = BehaviorDecision(
        tone=TonePolicy.SERIOUS,
        challenge=ChallengePolicy.HIGH,
        humor=HumorPolicy.DISABLED,
        reasoning=ReasoningPolicy.ANALYTICAL,
        explanation=ExplanationPolicy.DETAILED,
        confidence=ConfidencePolicy.DIRECT,
        collaboration=CollaborationPolicy.PARTNER,
    )
    report = reflect(
        "Production is down, restore the database",
        "I am restoring the database now.",
        evaluation=make_evaluation(behavior=behavior),
    )
    assert report.behavior_used == "serious"
    assert report.reasoning_used == "analytical"


def test_behavior_reported_unknown_without_evaluation():
    report = reflect("Fix the bug", "Fixed.")
    assert report.behavior_used == "unknown"
    assert report.reasoning_used == "unknown"


def test_response_length_reported():
    report = reflect("Do it", "one two three four five")
    assert report.response_length == 5


def test_completion_status_variants():
    engine = ReflectionEngine()
    assert engine.reflect("m", "Done.").completion_status == CompletionStatus.COMPLETED
    assert (
        engine.reflect("m", "I cannot do that without approval.").completion_status
        == CompletionStatus.REFUSED
    )
    assert engine.reflect("m", "   ").completion_status == CompletionStatus.NO_RESPONSE


# ---------------------------------------------------------------------------
# Memory usage
# ---------------------------------------------------------------------------


def test_memory_usage_visible():
    visible = [
        VisibleMemory(
            memory_id="m1",
            reason="rule 5: workflow continuation",
            visibility_type=VisibilityType.ALLOW,
        )
    ]
    report = reflect(
        "Continue the current task",
        "Done.",
        evaluation=make_evaluation(visible=visible),
    )
    assert report.memory_usage == MemoryUsage.VISIBLE


def test_memory_usage_summarized():
    summary = MemoryVisibilitySummary(
        total_count=7,
        primary_type="project",
        type_counts={"project": 7},
        importance_bucket="high",
        recency_label="recent",
        top_tags=["python"],
        summary_text="7 related project memories",
    )
    report = reflect(
        "What is the status of my project?",
        "It is on track.",
        evaluation=make_evaluation(summary=summary),
    )
    assert report.memory_usage == MemoryUsage.SUMMARIZED


def test_memory_usage_none_by_default():
    report = reflect("Hello there", "Hi!")
    assert report.memory_usage == MemoryUsage.NONE


# ---------------------------------------------------------------------------
# Approval / risk flags
# ---------------------------------------------------------------------------


def test_approval_flags_reflected():
    context = CapContextView(requires_approval=True, high_risk=True, sensitive=True)
    report = reflect(
        "Delete the database",
        "I cannot do that without approval.",
        cap_context=context,
    )
    assert report.approval_required is True
    assert report.risk_level == RiskLevel.HIGH


def test_approval_only_maps_to_low_risk():
    report = reflect("m", "r", cap_context=CapContextView(requires_approval=True))
    assert report.approval_required is True
    assert report.risk_level == RiskLevel.LOW


def test_sensitive_maps_to_medium_risk():
    report = reflect("m", "r", cap_context=CapContextView(sensitive=True))
    assert report.approval_required is False
    assert report.risk_level == RiskLevel.MEDIUM


def test_no_cap_context_is_no_risk():
    report = reflect("m", "r")
    assert report.approval_required is False
    assert report.risk_level == RiskLevel.NONE


# ---------------------------------------------------------------------------
# Descriptive, never prescriptive
# ---------------------------------------------------------------------------


def test_summary_is_descriptive_not_prescriptive():
    report = reflect("Fix the bug", "The bug is fixed.")
    summary = report.interaction_summary.lower()
    assert "classified as" in summary
    assert "should" not in summary
    assert "must" not in summary


def test_summary_reports_behavior_and_memory_when_present():
    visible = [
        VisibleMemory(
            memory_id="m1",
            reason="rule 5",
            visibility_type=VisibilityType.ALLOW,
        )
    ]
    report = reflect(
        "Continue the current task",
        "Done.",
        evaluation=make_evaluation(visible=visible),
    )
    summary = report.interaction_summary.lower()
    assert "memory usage was visible" in summary
    assert "professional behavior" in summary


# ---------------------------------------------------------------------------
# No storage access, no learning, no memory updates
# ---------------------------------------------------------------------------


def test_reflect_accepts_only_structured_inputs():
    signature = inspect.signature(ReflectionEngine.reflect)
    params = signature.parameters
    assert set(params) == {
        "self",
        "message",
        "response",
        "evaluation",
        "behavior",
        "visible_memories",
        "visibility_summary",
        "cap_context",
        "conversation_metadata",
        "prompt_composition",
    }


def test_engine_exposes_no_storage_or_learning_methods():
    methods = {name for name in dir(ReflectionEngine) if not name.startswith("_")}
    assert methods == {"reflect"}


def test_no_learning_performed():
    engine = ReflectionEngine()
    first = engine.reflect("Explain recursion", "Recursion is when a function calls itself.")
    second = engine.reflect("Explain recursion", "Recursion is when a function calls itself.")
    assert first == second
    assert vars(engine) == {}
    flat = str(first.model_dump()).lower()
    for field in (
        "learning",
        "score",
        "preference",
        "relationship",
        "feedback",
        "reward",
        "update",
    ):
        assert field not in flat, field


def test_no_memory_updates():
    visible = [
        VisibleMemory(
            memory_id="m1",
            reason="rule 5",
            visibility_type=VisibilityType.ALLOW,
        )
    ]
    evaluation = make_evaluation(visible=visible)
    before = evaluation.model_dump()
    ids_before = [item.memory_id for item in evaluation.visible_memories]
    ReflectionEngine().reflect("Continue", "Done.", evaluation=evaluation)
    assert evaluation.model_dump() == before
    assert [item.memory_id for item in evaluation.visible_memories] == ids_before


def test_prompt_composition_is_not_modified():
    evaluation = make_evaluation()
    composition = PromptComposer().compose(evaluation)
    before = composition.model_dump()
    ReflectionEngine().reflect(
        "Refactor parser.py",
        "Done.",
        evaluation=evaluation,
        prompt_composition=composition,
    )
    assert composition.model_dump() == before


def test_report_has_no_provider_or_learning_fields():
    report = reflect("m", "r")
    flat = str(report.model_dump()).lower()
    for field in ("provider", "model_id", "prompt", "learning"):
        assert field not in flat, field


# ---------------------------------------------------------------------------
# Feature extraction + integration
# ---------------------------------------------------------------------------


def test_feature_extraction_is_deterministic():
    from app.personality import extract_reflection_features

    first = extract_reflection_features(message="Fix the bug", response="Done.")
    second = extract_reflection_features(message="Fix the bug", response="Done.")
    assert first == second
    assert first.user_word_count == 3
    assert first.response_word_count == 1
    assert first.user_goal_detected is True


def test_full_pipeline_from_engine_to_reflection():
    cap_context = CapContextView(workflow_phase="execution")
    metadata = ConversationMetadataView(session_message_count=3)
    evaluation = PersonalityEngine().evaluate(
        "Refactor the API client",
        cap_context=cap_context,
        conversation_metadata=metadata,
    )
    composition = PromptComposer().compose(
        evaluation,
        cap_context=cap_context,
        conversation_metadata=metadata,
    )
    report = ReflectionEngine().reflect(
        evaluation.message,
        "I refactored the API client into a smaller module.",
        evaluation=evaluation,
        cap_context=cap_context,
        conversation_metadata=metadata,
        prompt_composition=composition,
    )
    assert isinstance(report, ReflectionReport)
    assert report.behavior_used == evaluation.behavior.tone.value
    assert report.reasoning_used == evaluation.behavior.reasoning.value
    assert report.completion_status == CompletionStatus.COMPLETED
