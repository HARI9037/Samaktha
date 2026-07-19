"""Phase 3.3 — Skill Memory subsystem tests.

Validates:
- SkillMemoryStore exact match and duplicate handling logic.
- LearningEngine persisting only HIGH/MEDIUM confidence skills.
- MemoryManager delegating correctly.
- Structural purity of the LearningEngine.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from app.core.contracts.learning import LearningResult, SkillCandidate, SkillConfidence
from app.core.contracts.skills import SkillRecord, SkillSearchResult
from app.core.gambit.learning import LearningEngine
from app.memory.manager import MemoryManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _skill_record(
    name: str = "Test Skill",
    category: str = "test",
    tags: list[str] | None = None,
) -> SkillRecord:
    return SkillRecord(
        skill_id=f"skill-{uuid4()}",
        name=name,
        description="A test skill",
        category=category,
        confidence=SkillConfidence.HIGH,
        source_plan="plan-123",
        tags=tags or [],
    )


def _candidate(
    name: str = "Test Candidate",
    confidence: SkillConfidence = SkillConfidence.HIGH,
) -> SkillCandidate:
    return SkillCandidate(
        skill_id=f"cand-{uuid4()}",
        title=name,
        description="A test candidate",
        category="test",
        confidence=confidence,
        source_plan_id="plan-123",
        success_rate=1.0,
        times_observed=5,
        estimated_value=0.9,
    )


def _learning_result(candidates: list[SkillCandidate]) -> LearningResult:
    return LearningResult(
        learning_id="learn-123",
        candidates=candidates,
        discarded_candidates=[],
        summary="Test",
    )


# ---------------------------------------------------------------------------
# SkillMemoryStore Tests
# ---------------------------------------------------------------------------


def test_save_new_skill() -> None:
    manager = MemoryManager()
    skill = _skill_record()

    manager.save_skill(skill)

    retrieved = manager.get_skill(skill.skill_id)
    assert retrieved is not None
    assert retrieved.name == skill.name
    metrics = manager.get_skill_metrics()
    assert metrics["skills_saved"] == 1
    assert metrics["current_skill_count"] == 1


def test_duplicate_merge() -> None:
    """Duplicate skills (same name and category) merge rather than duplicate."""
    manager = MemoryManager()
    skill1 = _skill_record(name="Merge Me", category="general", tags=["a"])
    manager.save_skill(skill1)

    skill2 = _skill_record(name="Merge Me", category="general", tags=["b"])
    # ID is different but name and category match, so it's a duplicate
    manager.save_skill(skill2)

    skills = manager.list_skills()
    assert len(skills) == 1
    merged = skills[0]
    
    # It updates the existing record
    assert merged.skill_id == skill1.skill_id
    assert merged.usage_count == 1
    assert "a" in merged.tags and "b" in merged.tags

    metrics = manager.get_skill_metrics()
    assert metrics["duplicate_merges"] == 1
    assert metrics["skills_saved"] == 1
    assert metrics["current_skill_count"] == 1


def test_list_skills() -> None:
    manager = MemoryManager()
    manager.save_skill(_skill_record(name="A", category="c1"))
    manager.save_skill(_skill_record(name="B", category="c2"))

    assert len(manager.list_skills()) == 2


def test_search_by_name() -> None:
    manager = MemoryManager()
    manager.save_skill(_skill_record(name="Unique Alpha Sequence"))
    manager.save_skill(_skill_record(name="Beta Sequence"))

    results = manager.search_skills(query="alpha")
    assert len(results) == 1
    assert results[0].skill.name == "Unique Alpha Sequence"
    assert results[0].score > 0


def test_search_by_category() -> None:
    manager = MemoryManager()
    manager.save_skill(_skill_record(name="A", category="filesystem"))
    manager.save_skill(_skill_record(name="B", category="network"))

    results = manager.search_skills(category="filesystem")
    assert len(results) == 1
    assert results[0].skill.name == "A"


def test_search_by_tag() -> None:
    manager = MemoryManager()
    manager.save_skill(_skill_record(name="A", tags=["python", "script"]))
    manager.save_skill(_skill_record(name="B", tags=["bash", "script"]))

    results = manager.search_skills(tag="python")
    assert len(results) == 1
    assert results[0].skill.name == "A"


# ---------------------------------------------------------------------------
# LearningEngine Persistence Tests
# ---------------------------------------------------------------------------


def test_learning_engine_persists_high_and_medium_confidence() -> None:
    engine = LearningEngine()
    manager = MemoryManager()

    c1 = _candidate(name="High Conf", confidence=SkillConfidence.HIGH)
    c2 = _candidate(name="Med Conf", confidence=SkillConfidence.MEDIUM)
    result = _learning_result([c1, c2])

    engine.persist_learning_result(result, manager)

    skills = manager.list_skills()
    assert len(skills) == 2
    names = {s.name for s in skills}
    assert "High Conf" in names
    assert "Med Conf" in names


def test_learning_engine_rejects_low_confidence() -> None:
    engine = LearningEngine()
    manager = MemoryManager()

    c1 = _candidate(name="High Conf", confidence=SkillConfidence.HIGH)
    c2 = _candidate(name="Low Conf", confidence=SkillConfidence.LOW)
    result = _learning_result([c1, c2])

    engine.persist_learning_result(result, manager)

    skills = manager.list_skills()
    assert len(skills) == 1
    assert skills[0].name == "High Conf"


# ---------------------------------------------------------------------------
# Structural Purity Test
# ---------------------------------------------------------------------------


def test_learning_engine_does_not_import_forbidden_modules() -> None:
    """LearningEngine must not import runtime, workflow, or planner systems."""
    import inspect
    from app.core.gambit import learning as learning_module

    source = inspect.getsource(learning_module)

    forbidden = [
        "ProviderManager",
        "ToolManager",
        "ToolExecutor",
        "ProviderExecutor",
        "WorkflowEngine",
        "Runtime",
        "Planner",
        "ReflectionEngine",
    ]
    for symbol in forbidden:
        assert symbol not in source, (
            f"LearningEngine must not reference {symbol!r} — "
            "it is purely analytical and persistent-only."
        )
