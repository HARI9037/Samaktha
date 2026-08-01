"""Tests for the deterministic Memory Visibility Policy (Phase 9.2).

Covers the eight spec rules, deterministic summarization, determinism, and
backward compatibility with the Phase 9.1 engine/adapter.
"""

from types import SimpleNamespace

import pytest

from app.personality import (
    MAX_VISIBLE_MEMORIES,
    PersonalityEngine,
    RULE_DOCUMENT,
    RULE_GREETING,
    RULE_IDENTITY,
    RULE_PREFERENCE,
    RULE_PROFILE,
    RULE_PROJECT,
    RULE_TECHNICAL,
    RULE_WORKFLOW,
    MemoryView,
    VisibilityType,
    evaluate_visibility,
    normalize_item,
)


def make_item(
    memory_id: str,
    memory_type: str,
    content: str = "",
    *,
    tags=None,
    entities=None,
    source: str = "",
    importance: float = 0.5,
    created_at: str = "2025-01-01T00:00:00",
    last_accessed: str | None = None,
):
    return SimpleNamespace(
        id=memory_id,
        content=content,
        metadata={
            "memory_type": memory_type,
            "tags": tags or [],
            "entities": entities or [],
            "source": source,
            "importance": importance,
            "created_at": created_at,
            "last_accessed": last_accessed or created_at,
        },
    )


def project_item(memory_id: str, content: str, **kwargs):
    return make_item(
        memory_id,
        "knowledge",
        content,
        tags=["project", "knowledge"],
        source="project",
        **kwargs,
    )


PREFERENCE = make_item("p1", "preference", "I like Python", tags=["preference"])
IDE_PREFERENCE = make_item("p2", "preference", "I use VS Code", tags=["preference"])
WORKFLOW = make_item(
    "w1", "workflow", "My workflow is to run pytest first", tags=["workflow"]
)
PROJECT = project_item("k1", "I'm building Samaktha with FastAPI")
CONVERSATION = make_item("c1", "conversation", "User: hi", tags=["auto-saved", "conversation"])
DOCUMENT = make_item(
    "d1", "document", "Document: report.pdf\nSummary: Q3 figures", tags=["document"]
)
TOOL = make_item("t1", "tool", "I use git for version control", tags=["tool", "git"])


# ---------------------------------------------------------------------------
# Rules 1-2
# ---------------------------------------------------------------------------


def test_rule1_greeting_exposes_nothing():
    items = [PREFERENCE, IDE_PREFERENCE, WORKFLOW, PROJECT]
    engine = PersonalityEngine()
    result = engine.evaluate("Hi", items)
    assert result.greeting.is_greeting
    assert result.visible_memories == []
    assert result.visibility_summary is None
    assert result.visibility_rule == RULE_GREETING.rule_id


def test_rule2_identity_exposes_nothing():
    items = [PREFERENCE, IDE_PREFERENCE, WORKFLOW, PROJECT]
    engine = PersonalityEngine()
    result = engine.evaluate("Who are you?", items)
    assert result.identity.is_identity_query
    assert result.visible_memories == []
    assert result.visibility_rule == RULE_IDENTITY.rule_id


def test_greeting_reports_suppressed_count():
    engine = PersonalityEngine()
    result = engine.evaluate("Hello", [PREFERENCE, CONVERSATION, DOCUMENT])
    assert result.visible_memories == []
    assert result.visibility_summary is None
    assert result.visibility_rule == RULE_GREETING.rule_id
    assert result.suppressed_count == 3


# ---------------------------------------------------------------------------
# Rule 3 — profile questions
# ---------------------------------------------------------------------------


def test_rule3_profile_question_exposes_profile_types():
    items = [PREFERENCE, WORKFLOW, PROJECT, CONVERSATION, DOCUMENT, TOOL]
    result = PersonalityEngine().evaluate("What do you know about me?", items)
    visible_ids = {v.memory_id for v in result.visible_memories}
    assert visible_ids == {"p1", "w1", "k1", "c1"}
    assert result.visibility_rule == RULE_PROFILE.rule_id
    assert all(v.visibility_type == VisibilityType.ALLOW for v in result.visible_memories)
    assert result.visibility_summary is None


def test_rule3_variant_phrasing():
    result = PersonalityEngine().evaluate(
        "Tell me about me", [PREFERENCE, DOCUMENT]
    )
    assert {v.memory_id for v in result.visible_memories} == {"p1"}
    assert result.visibility_rule == RULE_PROFILE.rule_id


# ---------------------------------------------------------------------------
# Rule 4 — specific preference questions
# ---------------------------------------------------------------------------


def test_rule4_language_preference_exactly_one():
    items = [PREFERENCE, IDE_PREFERENCE, CONVERSATION]
    result = PersonalityEngine().evaluate(
        "Which programming language do I prefer?", items
    )
    assert result.visibility_rule == RULE_PREFERENCE.rule_id
    assert [v.memory_id for v in result.visible_memories] == ["p1"]


def test_rule4_ide_preference_exactly_one():
    items = [PREFERENCE, IDE_PREFERENCE, CONVERSATION]
    result = PersonalityEngine().evaluate("Which IDE do I use?", items)
    assert result.visibility_rule == RULE_PREFERENCE.rule_id
    assert [v.memory_id for v in result.visible_memories] == ["p2"]


def test_rule4_no_matching_preference_exposes_nothing():
    items = [PREFERENCE, IDE_PREFERENCE, CONVERSATION]
    result = PersonalityEngine().evaluate("Which database do I use?", items)
    assert result.visibility_rule == RULE_PREFERENCE.rule_id
    assert result.visible_memories == []
    assert result.visibility_summary is None


# ---------------------------------------------------------------------------
# Rule 5 — workflow continuation
# ---------------------------------------------------------------------------


def test_rule5_workflow_continuation_exposes_workflow_and_project():
    items = [WORKFLOW, PROJECT, IDE_PREFERENCE, CONVERSATION]
    result = PersonalityEngine().evaluate("Continue yesterday's work", items)
    assert result.visibility_rule == RULE_WORKFLOW.rule_id
    assert {v.memory_id for v in result.visible_memories} == {"w1", "k1"}
    assert result.visibility_summary is None


def test_rule5_resume_phrasing_suppresses_preferences():
    items = [WORKFLOW, IDE_PREFERENCE, PREFERENCE]
    result = PersonalityEngine().evaluate("Where did we stop?", items)
    assert {v.memory_id for v in result.visible_memories} == {"w1"}
    assert result.visibility_rule == RULE_WORKFLOW.rule_id


# ---------------------------------------------------------------------------
# Rule 6 — document-history questions
# ---------------------------------------------------------------------------


def test_rule6_document_history_exposes_documents_only():
    items = [DOCUMENT, CONVERSATION, PREFERENCE]
    result = PersonalityEngine().evaluate("Which PDF did I read today?", items)
    assert result.visibility_rule == RULE_DOCUMENT.rule_id
    assert [v.memory_id for v in result.visible_memories] == ["d1"]
    assert result.visibility_summary is None


def test_rule6_list_documents():
    result = PersonalityEngine().evaluate("List the documents I opened", [DOCUMENT])
    assert result.visibility_rule == RULE_DOCUMENT.rule_id
    assert [v.memory_id for v in result.visible_memories] == ["d1"]


# ---------------------------------------------------------------------------
# Rule 7 — general technical questions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("message", ["Explain recursion", "What is a pointer?"])
def test_rule7_general_technical_exposes_nothing(message):
    items = [PREFERENCE, WORKFLOW, PROJECT, DOCUMENT]
    result = PersonalityEngine().evaluate(message, items)
    assert result.visibility_rule == RULE_TECHNICAL.rule_id
    assert result.visible_memories == []
    assert result.visibility_summary is None


# ---------------------------------------------------------------------------
# Rule 8 — project-status questions
# ---------------------------------------------------------------------------


def test_rule8_project_status_exposes_project_and_workflow():
    items = [PROJECT, WORKFLOW, IDE_PREFERENCE, CONVERSATION]
    result = PersonalityEngine().evaluate("How is Samaktha progressing?", items)
    assert result.visibility_rule == RULE_PROJECT.rule_id
    assert {v.memory_id for v in result.visible_memories} == {"k1", "w1"}
    assert result.visibility_summary is None


def test_rule8_status_variants():
    for message in (
        "What's the status of my project?",
        "Where are we with Samaktha?",
        "How is the parser work coming along?",
    ):
        result = PersonalityEngine().evaluate(message, [PROJECT, WORKFLOW, IDE_PREFERENCE])
        assert result.visibility_rule == RULE_PROJECT.rule_id, message
        assert {v.memory_id for v in result.visible_memories} == {"k1", "w1"}


# ---------------------------------------------------------------------------
# Default behavior
# ---------------------------------------------------------------------------


def test_default_passthrough_when_no_rule_matches():
    items = [PREFERENCE, WORKFLOW, PROJECT]
    result = PersonalityEngine().evaluate("Please fix the bug in parser.py", items)
    assert result.visibility_rule is None
    assert {v.memory_id for v in result.visible_memories} == {"p1", "w1", "k1"}
    assert all(v.visibility_type == VisibilityType.ALLOW for v in result.visible_memories)


def test_empty_message_default_passthrough():
    result = PersonalityEngine().evaluate("", [PREFERENCE])
    assert result.visible_memories
    assert result.visibility_rule is None


# ---------------------------------------------------------------------------
# Summarization
# ---------------------------------------------------------------------------


def _many_project_items(n: int):
    return [
        project_item(f"pk{i}", f"Project fact number {i}", created_at="2025-01-01T00:00:00")
        for i in range(n)
    ]


def test_summarization_collapses_more_than_five():
    items = _many_project_items(MAX_VISIBLE_MEMORIES + 1)
    result = PersonalityEngine().evaluate("What do you know about me?", items)
    assert result.visibility_summary is not None
    summary = result.visibility_summary
    assert summary.total_count == MAX_VISIBLE_MEMORIES + 1
    assert summary.summary_text == f"{MAX_VISIBLE_MEMORIES + 1} related project memories"
    assert summary.primary_type == "knowledge"
    assert summary.type_counts == {"knowledge": MAX_VISIBLE_MEMORIES + 1}
    assert all(
        v.visibility_type == VisibilityType.SUMMARIZE
        for v in result.visible_memories
    )
    assert len(result.visible_memories) == MAX_VISIBLE_MEMORIES + 1


def test_summarization_mixed_types_text():
    items = [
        make_item("a", "knowledge", "fact A", tags=["knowledge"]),
        make_item("b", "knowledge", "fact B", tags=["knowledge"]),
        make_item("c", "preference", "pref C", tags=["preference"]),
        make_item("d", "preference", "pref D", tags=["preference"]),
        make_item("e", "workflow", "wf E", tags=["workflow"]),
        make_item("f", "workflow", "wf F", tags=["workflow"]),
    ]
    result = PersonalityEngine().evaluate("What do you know about me?", items)
    assert result.visibility_summary is not None
    assert result.visibility_summary.summary_text == "6 related memories"
    assert result.visibility_summary.primary_type == "knowledge"
    assert result.visibility_summary.type_counts == {
        "knowledge": 2,
        "preference": 2,
        "workflow": 2,
    }
    assert result.visibility_summary.importance_bucket == "medium"
    assert result.visibility_summary.recency_label == "older"
    assert result.visibility_summary.top_tags
    assert result.visibility_summary.total_count == 6


def test_five_or_fewer_stays_individual():
    items = [PREFERENCE, WORKFLOW, PROJECT, CONVERSATION]
    result = PersonalityEngine().evaluate("What do you know about me?", items)
    assert result.visibility_summary is None
    assert len(result.visible_memories) == 4
    assert all(v.visibility_type == VisibilityType.ALLOW for v in result.visible_memories)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_policy_is_deterministic():
    engine = PersonalityEngine()
    items = [PREFERENCE, WORKFLOW, PROJECT, DOCUMENT, TOOL]
    first = engine.evaluate("What do you know about me?", items)
    second = engine.evaluate("What do you know about me?", items)
    assert first.visible_memories == second.visible_memories
    assert first.visibility_summary == second.visibility_summary
    assert first == second


def test_evaluate_visibility_is_deterministic():
    views = [normalize_item(PREFERENCE), normalize_item(WORKFLOW)]
    assert evaluate_visibility("Continue yesterday's work", views) == evaluate_visibility(
        "Continue yesterday's work", views
    )


# ---------------------------------------------------------------------------
# Rule priority
# ---------------------------------------------------------------------------


def test_project_rule_wins_over_technical():
    views = [normalize_item(PROJECT), normalize_item(WORKFLOW)]
    match = evaluate_visibility("What is the status of my project?", views)
    assert match.rule_id == RULE_PROJECT.rule_id
    assert [v.memory_id for v in match.allowed] == ["k1", "w1"]


def test_rule_order_profile_before_preference():
    views = [normalize_item(PREFERENCE), normalize_item(CONVERSATION)]
    match = evaluate_visibility("What do you know about me?", views)
    assert match.rule_id == RULE_PROFILE.rule_id


# ---------------------------------------------------------------------------
# normalize_item
# ---------------------------------------------------------------------------


def test_normalize_item_memory_shape():
    view = normalize_item(PREFERENCE)
    assert isinstance(view, MemoryView)
    assert view.memory_id == "p1"
    assert view.memory_type == "preference"
    assert "python" in view.content.lower()
    assert "preference" in view.tags
    assert view.importance == 0.5


def test_normalize_item_document_wrapper_shape():
    item = SimpleNamespace(
        document_id="doc-abc",
        content="Document: report.pdf\nSummary: Q3 figures",
        metadata={"memory_type": "document", "doc_name": "report.pdf", "source_path": "x"},
    )
    view = normalize_item(item)
    assert view.memory_id == "doc-abc"
    assert view.memory_type == "document"


def test_normalize_item_skill_shape():
    item = SimpleNamespace(skill_id="sk-1", metadata={"memory_type": "skill", "tags": ["skill"]})
    view = normalize_item(item)
    assert view.memory_id == "sk-1"
    assert view.memory_type == "skill"


def test_normalize_item_none_returns_none():
    assert normalize_item(None) is None


def test_is_project_detection():
    assert normalize_item(PROJECT).is_project()
    assert not normalize_item(PREFERENCE).is_project()


# ---------------------------------------------------------------------------
# Backward compatibility with Phase 9.1
# ---------------------------------------------------------------------------


def test_evaluate_without_memories_keeps_identity_behavior():
    engine = PersonalityEngine()
    result = engine.evaluate("Who are you?")
    assert result.identity.is_identity_query
    assert result.visible_memories == []
    assert result.visibility_rule == RULE_IDENTITY.rule_id


def test_evaluation_has_no_provider_fields():
    result = PersonalityEngine().evaluate("Hi")
    flat = str(result.model_dump()).lower()
    for field in ("provider", "model_id", "prompt", "response"):
        assert field not in flat, field
