"""Tests for the Dynamic Prompt Composer (Phase 9.4).

Verifies the ten spec acceptance points:
    - identical inputs produce identical prompts
    - suppressed memories never appear
    - summarized memories appear correctly (as a summary, not individually)
    - behavior sections reflect the BehaviorDecision verbatim
    - identity stays constant across interactions
    - prompt ordering is deterministic
    - the composer never accesses storage
    - the composer performs no personality logic
    - the composer never performs retrieval
    - the composer is provider-independent
plus integration with the PersonalityEngine and freedom from provider/prompt
fields. No randomness, no LLM calls, no storage.
"""

from types import SimpleNamespace

from app.personality import (
    SAMAKTHA_IDENTITY_PROFILE,
    BehaviorDecision,
    CapContextView,
    ChallengePolicy,
    CollaborationPolicy,
    ConfidencePolicy,
    ConversationMetadataView,
    ExplanationPolicy,
    GreetingDecision,
    HumorPolicy,
    IdentityDecision,
    PersonalityEngine,
    PersonalityEvaluation,
    PromptComposer,
    PromptComposition,
    ReasoningPolicy,
    TonePolicy,
    VisibilityType,
    VisibleMemory,
    identity_to_provider_context,
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
    suppressed: int = 0,
) -> PersonalityEvaluation:
    return PersonalityEvaluation(
        message=message,
        identity=IdentityDecision(is_identity_query=False),
        greeting=GreetingDecision(is_greeting=False),
        profile=SAMAKTHA_IDENTITY_PROFILE,
        behavior=behavior,
        visible_memories=visible or [],
        visibility_summary=summary,
        suppressed_count=suppressed,
    )


def compose(
    evaluation: PersonalityEvaluation,
    *,
    cap_context: CapContextView | None = None,
    conversation_metadata: ConversationMetadataView | None = None,
) -> PromptComposition:
    return PromptComposer().compose(
        evaluation,
        cap_context=cap_context,
        conversation_metadata=conversation_metadata,
    )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_identical_inputs_produce_identical_prompts():
    context = CapContextView(workflow_phase="planning", system_context="sandbox")
    metadata = ConversationMetadataView(session_message_count=5)
    first = compose(make_evaluation(), cap_context=context, conversation_metadata=metadata)
    second = compose(make_evaluation(), cap_context=context, conversation_metadata=metadata)
    assert first == second
    assert first.system_prompt == second.system_prompt
    assert first.model_dump() == second.model_dump()


def test_same_inputs_different_composer_instances():
    context = CapContextView(workflow_phase="execution")
    first = PromptComposer().compose(make_evaluation(), cap_context=context)
    second = PromptComposer().compose(make_evaluation(), cap_context=context)
    assert first.system_prompt == second.system_prompt


# ---------------------------------------------------------------------------
# Memory rendering: suppressed vs summarized vs visible
# ---------------------------------------------------------------------------


def test_suppressed_memories_never_appear():
    allowed = [
        VisibleMemory(
            memory_id="allowed_1",
            reason="rule 8: project status",
            visibility_type=VisibilityType.ALLOW,
            content="current status: refactoring parser.py",
        )
    ]
    evaluation = make_evaluation(visible=allowed, suppressed=2)
    composition = compose(evaluation)
    assert "allowed_1" not in composition.memory_section
    assert "current status: refactoring parser.py" in composition.memory_section
    assert "suppressed" not in composition.system_prompt.lower()
    assert "suppressed" not in composition.memory_section.lower()


def test_suppressed_only_yields_empty_memory_section():
    evaluation = make_evaluation(visible=[], suppressed=4)
    composition = compose(evaluation)
    assert composition.memory_section == ""
    assert "Relevant memories" not in composition.system_prompt


def test_summarized_memories_appear_as_summary_only():
    summary = MemoryVisibilitySummary(
        total_count=7,
        primary_type="project",
        type_counts={"project": 7},
        importance_bucket="high",
        recency_label="recent",
        top_tags=["python", "api"],
        summary_text="7 related project memories",
    )
    visible = [
        VisibleMemory(
            memory_id=f"p{i}",
            reason="rule 8: project status: collapsed into summary",
            visibility_type=VisibilityType.SUMMARIZE,
        )
        for i in range(7)
    ]
    composition = compose(make_evaluation(visible=visible, summary=summary))
    assert "7 related project memories" in composition.memory_section
    assert "Total: 7" in composition.memory_section
    assert "Primary type: project" in composition.memory_section
    assert "Importance: high" in composition.memory_section
    assert "Recency: recent" in composition.memory_section
    assert "Top tags: python, api" in composition.memory_section
    for i in range(7):
        assert f"p{i}" not in composition.memory_section
        assert f"p{i}" not in composition.system_prompt


def test_visible_memories_list_when_no_summary():
    visible = [
        VisibleMemory(
            memory_id="m1",
            reason="rule 5: workflow continuation",
            visibility_type=VisibilityType.ALLOW,
            content="workflow continuation checkpoint",
        ),
        VisibleMemory(
            memory_id="m2",
            reason="rule 5: workflow continuation",
            visibility_type=VisibilityType.ALLOW,
            content="parser tests passing",
        ),
    ]
    composition = compose(make_evaluation(visible=visible))
    assert "m1" not in composition.memory_section
    assert "m2" not in composition.memory_section
    assert "- workflow continuation checkpoint" in composition.memory_section
    assert "- parser tests passing" in composition.memory_section
    assert "allow" not in composition.memory_section.lower()
    assert "summary" not in composition.memory_section.lower()


def test_memory_section_ignores_the_message():
    visible = [
        VisibleMemory(
            memory_id="m1",
            reason="rule 6: document history",
            visibility_type=VisibilityType.ALLOW,
            content="opened design.md and roadmap.md",
        )
    ]
    first = compose(make_evaluation(message="Which documents did I open?", visible=visible))
    second = compose(make_evaluation(message="How did the meeting go?", visible=visible))
    assert first.memory_section == second.memory_section
    assert "opened design.md and roadmap.md" in first.memory_section


# ---------------------------------------------------------------------------
# Behavior rendering (verbatim, no re-evaluation)
# ---------------------------------------------------------------------------


def test_behavior_section_reflects_behavior_decision_verbatim():
    behavior = BehaviorDecision(
        tone=TonePolicy.ENCOURAGING,
        challenge=ChallengePolicy.HIGH,
        humor=HumorPolicy.DISABLED,
        reasoning=ReasoningPolicy.STRATEGIC,
        explanation=ExplanationPolicy.DETAILED,
        confidence=ConfidencePolicy.EXPLICIT_UNCERTAINTY,
        collaboration=CollaborationPolicy.ASSIST,
    )
    section = compose(make_evaluation(behavior=behavior)).behavior_section
    assert "- Tone: encouraging" in section
    assert "- Challenge: high" in section
    assert "- Humor: disabled" in section
    assert "- Reasoning: strategic" in section
    assert "- Explanation: detailed" in section
    assert "- Confidence: explicit_uncertainty" in section
    assert "- Collaboration: assist" in section


def test_behavior_section_is_not_derived_from_the_message():
    # A combination the policies would never produce for this command-like
    # message: the composer must render it verbatim, proving no re-evaluation.
    behavior = BehaviorDecision(
        tone=TonePolicy.SERIOUS,
        challenge=ChallengePolicy.NONE,
        humor=HumorPolicy.PLAYFUL,
        reasoning=ReasoningPolicy.CREATIVE,
        explanation=ExplanationPolicy.BRIEF,
        confidence=ConfidencePolicy.DIRECT,
        collaboration=CollaborationPolicy.PARTNER,
    )
    section = compose(
        make_evaluation(message="Please fix the bug in parser.py", behavior=behavior)
    ).behavior_section
    assert "- Tone: serious" in section
    assert "- Humor: playful" in section
    assert "- Collaboration: partner" in section


# ---------------------------------------------------------------------------
# Identity (static)
# ---------------------------------------------------------------------------


def test_identity_section_is_constant_across_interactions():
    first = compose(make_evaluation(message="one"))
    second = compose(make_evaluation(message="two"))
    assert first.identity_section == second.identity_section
    assert first.identity_section.startswith("You are Samaktha.")
    assert "Mission:" in first.identity_section
    assert "Capabilities:" in first.identity_section
    assert "Limitations:" in first.identity_section
    assert "Philosophy:" in first.identity_section


def test_identity_section_matches_the_legacy_adapter():
    composition = compose(make_evaluation())
    assert composition.identity_section == identity_to_provider_context(
        SAMAKTHA_IDENTITY_PROFILE
    )


# ---------------------------------------------------------------------------
# Ordering + final system_prompt
# ---------------------------------------------------------------------------


def test_prompt_ordering_is_deterministic():
    composition = compose(
        make_evaluation(
            visible=[
                VisibleMemory(
                    memory_id="m1",
                    reason="rule 5",
                    visibility_type=VisibilityType.ALLOW,
                    content="workflow continuation",
                )
            ]
        ),
        cap_context=CapContextView(workflow_phase="execution"),
        conversation_metadata=ConversationMetadataView(session_message_count=2),
    )
    sections = (
        composition.identity_section,
        composition.behavior_section,
        composition.context_section,
        composition.memory_section,
        composition.task_section,
    )
    expected = "\n\n".join(section for section in sections if section)
    assert composition.system_prompt == expected
    assert composition.system_prompt.startswith("You are Samaktha.")
    assert composition.system_prompt.endswith(composition.task_section)


def test_empty_sections_are_omitted_from_final_prompt():
    composition = compose(make_evaluation())
    assert composition.context_section == ""
    assert composition.memory_section == ""
    assert composition.system_prompt == "\n\n".join(
        (
            composition.identity_section,
            composition.behavior_section,
            composition.task_section,
        )
    )


def test_task_section_carries_message_unmodified():
    message = "  Refactor parser.py  "
    composition = compose(make_evaluation(message=message))
    assert composition.task_section == f"Current task:\n{message}"
    assert composition.system_prompt.endswith(message)


def test_context_section_renders_cap_approved_info_only():
    composition = compose(
        make_evaluation(),
        cap_context=CapContextView(
            workflow_phase="execution",
            system_context="sandbox shell",
            is_memory_recall=True,
            requires_approval=True,
            high_risk=True,
            sensitive=True,
        ),
        conversation_metadata=ConversationMetadataView(session_message_count=5),
    )
    context = composition.context_section
    assert "- Workflow phase: execution" in context
    assert "- System context: sandbox shell" in context
    assert "- This interaction is a memory recall." in context
    assert "- Governance approval is required." in context
    assert "- High risk" in context
    assert "- Sensitive" in context
    assert "- Session message count: 5" in context


# ---------------------------------------------------------------------------
# No storage access, no retrieval, no personality logic, provider-independent
# ---------------------------------------------------------------------------


def test_composer_receives_only_structured_data():
    import inspect

    signature = inspect.signature(PromptComposer.compose)
    params = signature.parameters
    assert set(params) == {
        "self",
        "evaluation",
        "cap_context",
        "conversation_metadata",
        "include_current_task",
    }
    assert params["cap_context"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["conversation_metadata"].kind is inspect.Parameter.KEYWORD_ONLY


def test_memory_section_never_fabricates_ids():
    visible = [
        VisibleMemory(
            memory_id="known_id",
            reason="rule 5",
            visibility_type=VisibilityType.ALLOW,
            content="acme project kickoff summary",
        )
    ]
    composition = compose(
        make_evaluation(message="What do you remember about acme project?", visible=visible)
    )
    assert composition.memory_section == (
        "Relevant memories:\n- acme project kickoff summary"
    )


def test_composition_has_only_string_sections():
    composition = compose(make_evaluation())
    dump = composition.model_dump()
    assert set(dump) == {
        "identity_section",
        "behavior_section",
        "context_section",
        "memory_section",
        "task_section",
        "system_prompt",
    }
    assert all(isinstance(value, str) for value in dump.values())


def test_composition_is_provider_independent():
    composition = compose(make_evaluation())
    flat = str(composition.model_dump()).lower()
    for field in (
        "provider",
        "model_id",
        "model_name",
        "openai",
        "anthropic",
        "claude",
        "gemini",
    ):
        assert field not in flat, field


# ---------------------------------------------------------------------------
# PersonalityEngine integration
# ---------------------------------------------------------------------------


def make_memory_item(memory_id: str, memory_type: str, tags: list[str]):
    return SimpleNamespace(
        id=memory_id,
        content="content",
        metadata={
            "memory_type": memory_type,
            "tags": tags,
            "entities": [],
            "source": "",
            "importance": 0.8,
            "created_at": "2025-01-01T00:00:00",
            "last_accessed": "2025-01-01T00:00:00",
        },
    )


def test_full_pipeline_from_engine_to_composer():
    evaluation = PersonalityEngine().evaluate(
        "Which documents did I open last week?",
        retrieved_memories=[
            make_memory_item("doc_1", "document", ["document"]),
            make_memory_item("doc_2", "document", ["document"]),
        ],
        cap_context=CapContextView(workflow_phase="execution"),
        conversation_metadata=ConversationMetadataView(session_message_count=9),
    )
    composition = PromptComposer().compose(
        evaluation,
        cap_context=CapContextView(workflow_phase="execution"),
        conversation_metadata=ConversationMetadataView(session_message_count=9),
    )
    assert isinstance(composition, PromptComposition)
    assert composition.behavior_section
    assert composition.task_section.endswith("Which documents did I open last week?")
    assert composition.system_prompt.startswith("You are Samaktha.")
