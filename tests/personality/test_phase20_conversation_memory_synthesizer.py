from app.personality.conversation_memory_synthesizer import ConversationMemorySynthesizer
from app.personality.models import (
    BehaviorDecision,
    ChallengePolicy,
    ConversationIntent,
    GreetingDecision,
    GreetingKind,
    IdentityDecision,
    IdentityProfile,
    TonePolicy,
    HumorPolicy,
    ReasoningPolicy,
    ExplanationPolicy,
    ConfidencePolicy,
    PersonalityEvaluation,
    VisibleMemory,
    VisibilityType,
)


def _evaluation(message: str, memories: list[VisibleMemory], *, summary=None) -> PersonalityEvaluation:
    return PersonalityEvaluation(
        message=message,
        identity=IdentityDecision(is_identity_query=False),
        greeting=GreetingDecision(is_greeting=False, kind=GreetingKind.GENERIC),
        profile=IdentityProfile(
            name="Samaktha",
            mission="",
            description="",
            capabilities=[],
            limitations=[],
            philosophy="",
        ),
        behavior=BehaviorDecision(
            tone=TonePolicy.PROFESSIONAL,
            challenge=ChallengePolicy.NORMAL,
            humor=HumorPolicy.DISABLED,
            reasoning=ReasoningPolicy.ANALYTICAL,
            explanation=ExplanationPolicy.NORMAL,
            confidence=ConfidencePolicy.QUALIFIED,
        ),
        visible_memories=memories,
        visibility_summary=summary,
    )


def _memory(memory_id: str, content: str, *, session_id: str = "s1", freshness: str = "active", confidence: float = 0.9) -> VisibleMemory:
    return VisibleMemory(
        memory_id=memory_id,
        reason="test",
        visibility_type=VisibilityType.ALLOW,
        content=content,
        provenance=f"session:{session_id}:{memory_id}",
        session_id=session_id,
        confidence=confidence,
        freshness=freshness,
    )


def test_topic_clustering_collapses_related_memories():
    synth = ConversationMemorySynthesizer()
    text = synth.synthesize(
        _evaluation(
            "What do you remember?",
            [
                _memory("m1", "Phase 17 Intelligence Architecture"),
                _memory("m2", "Phase 17 RetrievalEngine"),
                _memory("m3", "Phase 17 Learning pipeline"),
            ],
        )
    )
    assert "Phase 17 Intelligence Architecture" in text
    assert "3 mentions" in text
    assert "raw transcript" not in text.lower()


def test_timeline_mode_orders_recent_evidence():
    synth = ConversationMemorySynthesizer()
    text = synth.synthesize(
        _evaluation(
            "What happened yesterday?",
            [
                _memory("m1", "Earlier this week we reviewed Phase 19", session_id="s2", freshness="within_a_month"),
                _memory("m2", "Yesterday we discussed Phase 20", session_id="s3", freshness="recent"),
            ],
        ),
        mode="auto",
    )
    assert text.startswith("Timeline:")
    assert "Yesterday we discussed Phase 20" in text


def test_project_mode_summarizes_progress():
    synth = ConversationMemorySynthesizer()
    text = synth.synthesize(
        _evaluation(
            "What were we building?",
            [
                _memory("m1", "Phase 17 completed"),
                _memory("m2", "Phase 18 completed"),
                _memory("m3", "Phase 19 completed"),
                _memory("m4", "Phase 20 completed"),
            ],
        ),
        mode="auto",
    )
    assert text.startswith("Project: Samaktha")
    assert "Current progress:" in text
    assert "Phase 20 Conversational Intelligence" in text


def test_duplicate_memories_collapse():
    synth = ConversationMemorySynthesizer()
    text = synth.synthesize(
        _evaluation(
            "What do you remember?",
            [
                _memory("m1", "Phase 18 Runtime Parallel Execution"),
                _memory("m2", "Phase 18 Runtime Parallel Execution"),
                _memory("m3", "Phase 18 Runtime Parallel Execution"),
            ],
        )
    )
    assert "3 mentions" in text
    assert text.count("Phase 18 Runtime Parallel Execution") == 1


def test_bugs_and_decisions_modes_are_deterministic():
    synth = ConversationMemorySynthesizer()
    bug_text = synth.synthesize(
        _evaluation(
            "What bugs did we fix?",
            [
                _memory("m1", "Fixed runtime scheduling issues"),
                _memory("m2", "Resolved timestamp normalization bug"),
            ],
        ),
        mode="auto",
    )
    decision_text = synth.synthesize(
        _evaluation(
            "What decisions did we make?",
            [
                _memory("m3", "Decision: keep CAP governance first"),
                _memory("m4", "Decision: keep Runtime execution isolated"),
            ],
        ),
        mode="auto",
    )
    assert "Bug summary:" in bug_text
    assert "Architecture decisions:" in decision_text


def test_explainability_preserves_provenance():
    synth = ConversationMemorySynthesizer()
    explanation = synth.explain(
        _evaluation(
            "How do you know that?",
            [
                _memory("m1", "Phase 20 conversational intelligence", session_id="session-a", confidence=0.8),
                _memory("m2", "Phase 19 cognitive planning", session_id="session-b", confidence=0.7),
            ],
        )
    )
    assert "session-a" in explanation
    assert "session-b" in explanation
    assert "Evidence count: 2" in explanation
