"""Phase 3.5 — Skill Lifecycle Management Tests.

Validates deterministic lifecycle operations:
- Confidence decay on stale skills
- Usage, success, and failure tracking
- Deprecation and archival
- Duplicate consolidation
- Planner filtering by lifecycle_state
- Lifecycle maintenance
- Structural purity
"""
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from app.core.contracts.learning import SkillConfidence
from app.core.contracts.skills import SkillLifecycleState, SkillRecord, SkillSearchResult
from app.core.gambit.planner import Planner
from app.memory.manager import MemoryManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _skill(
    name: str = "Test Skill",
    category: str = "general",
    confidence: SkillConfidence = SkillConfidence.HIGH,
    tags: list[str] | None = None,
    created_at: datetime | None = None,
    usage_count: int = 0,
    success_count: int = 0,
    failure_count: int = 0,
) -> SkillRecord:
    return SkillRecord(
        skill_id=f"skill-{uuid4()}",
        name=name,
        category=category,
        description=f"Description for {name}",
        confidence=confidence,
        source_plan="plan-x",
        tags=tags or [],
        created_at=created_at or datetime.utcnow(),
        usage_count=usage_count,
        success_count=success_count,
        failure_count=failure_count,
    )


# ---------------------------------------------------------------------------
# Tests: Usage Tracking
# ---------------------------------------------------------------------------


def test_record_skill_use_increments_usage_count() -> None:
    manager = MemoryManager()
    skill = _skill(name="UsageSkill")
    manager.save_skill(skill)

    manager.record_skill_use(skill.skill_id)
    manager.record_skill_use(skill.skill_id)

    retrieved = manager.get_skill(skill.skill_id)
    assert retrieved is not None
    assert retrieved.usage_count == 2
    assert retrieved.last_used_at is not None


def test_record_skill_use_does_not_affect_deprecated() -> None:
    manager = MemoryManager()
    skill = _skill(name="DeprecatedUsage")
    manager.save_skill(skill)
    manager.deprecate_skill(skill.skill_id)
    original_count = skill.usage_count

    manager.record_skill_use(skill.skill_id)

    retrieved = manager.get_skill(skill.skill_id)
    assert retrieved.usage_count == original_count  # No increment on deprecated


# ---------------------------------------------------------------------------
# Tests: Success/Failure Tracking
# ---------------------------------------------------------------------------


def test_record_skill_success_increments_and_recomputes() -> None:
    manager = MemoryManager()
    skill = _skill(name="SuccessSkill", success_count=3, failure_count=1)
    manager.save_skill(skill)

    manager.record_skill_success(skill.skill_id)

    retrieved = manager.get_skill(skill.skill_id)
    assert retrieved.success_count == 4
    assert retrieved.failure_count == 1
    assert retrieved.success_rate == pytest.approx(4 / 5)


def test_record_skill_failure_increments_and_recomputes() -> None:
    manager = MemoryManager()
    skill = _skill(name="FailureSkill", success_count=2, failure_count=2)
    manager.save_skill(skill)

    manager.record_skill_failure(skill.skill_id)

    retrieved = manager.get_skill(skill.skill_id)
    assert retrieved.failure_count == 3
    assert retrieved.success_rate == pytest.approx(2 / 5)


def test_record_skill_failure_auto_deprecates_below_threshold() -> None:
    """A skill with >= 5 runs and < 30% success rate is auto-deprecated."""
    manager = MemoryManager()
    skill = _skill(name="BadSkill", success_count=1, failure_count=3)
    manager.save_skill(skill)

    # 5th run, all failures → success_rate = 1/5 = 0.20 < 0.30
    manager.record_skill_failure(skill.skill_id)

    retrieved = manager.get_skill(skill.skill_id)
    assert retrieved.lifecycle_state == SkillLifecycleState.DEPRECATED
    assert "deprecation_reason" in retrieved.metadata


# ---------------------------------------------------------------------------
# Tests: Deprecation & Archival
# ---------------------------------------------------------------------------


def test_deprecate_skill() -> None:
    manager = MemoryManager()
    skill = _skill(name="DeprecateMe")
    manager.save_skill(skill)

    manager.deprecate_skill(skill.skill_id, reason="manual test")

    retrieved = manager.get_skill(skill.skill_id)
    assert retrieved.is_deprecated
    assert retrieved.metadata.get("deprecation_reason") == "manual test"


def test_archive_skill() -> None:
    manager = MemoryManager()
    skill = _skill(name="ArchiveMe")
    manager.save_skill(skill)

    manager.archive_skill(skill.skill_id)

    retrieved = manager.get_skill(skill.skill_id)
    assert retrieved.is_archived


def test_list_deprecated_skills() -> None:
    manager = MemoryManager()
    s1 = _skill(name="A")
    s2 = _skill(name="B")
    manager.save_skill(s1)
    manager.save_skill(s2)
    manager.deprecate_skill(s1.skill_id)

    deprecated = manager.list_deprecated_skills()
    assert len(deprecated) == 1
    assert deprecated[0].name == "A"


def test_list_archived_skills() -> None:
    manager = MemoryManager()
    s1 = _skill(name="Active")
    s2 = _skill(name="Archived")
    manager.save_skill(s1)
    manager.save_skill(s2)
    manager.archive_skill(s2.skill_id)

    archived = manager.list_archived_skills()
    assert len(archived) == 1
    assert archived[0].name == "Archived"

    # Active still retrievable via list_skills
    assert len(manager.list_skills()) == 2


# ---------------------------------------------------------------------------
# Tests: Confidence Decay & Maintenance
# ---------------------------------------------------------------------------


def test_lifecycle_maintenance_decays_stale_high_to_medium() -> None:
    """A HIGH-confidence skill with no usage older than threshold → MEDIUM."""
    manager = MemoryManager()
    old_created = datetime.utcnow() - timedelta(days=60)
    skill = _skill(name="StaleHigh", confidence=SkillConfidence.HIGH, created_at=old_created)
    manager.save_skill(skill)

    result = manager.run_lifecycle_maintenance(stale_days=30)

    retrieved = manager.get_skill(skill.skill_id)
    assert retrieved.confidence == SkillConfidence.MEDIUM
    assert result["decayed"] == 1
    assert result["deprecated"] == 0


def test_lifecycle_maintenance_decays_medium_to_low_and_deprecates() -> None:
    """A MEDIUM-confidence skill with no usage older than threshold → LOW → DEPRECATED."""
    manager = MemoryManager()
    old_created = datetime.utcnow() - timedelta(days=60)
    skill = _skill(name="StaleMedium", confidence=SkillConfidence.MEDIUM, created_at=old_created)
    manager.save_skill(skill)

    result = manager.run_lifecycle_maintenance(stale_days=30)

    retrieved = manager.get_skill(skill.skill_id)
    assert retrieved.confidence == SkillConfidence.LOW
    assert retrieved.is_deprecated
    assert result["decayed"] == 1
    assert result["deprecated"] == 1


def test_lifecycle_maintenance_skips_used_skills() -> None:
    """A skill with last_used_at set is not stale even if old."""
    manager = MemoryManager()
    old_created = datetime.utcnow() - timedelta(days=60)
    skill = _skill(name="RecentlyUsed", confidence=SkillConfidence.HIGH, created_at=old_created)
    manager.save_skill(skill)
    # Simulate it having been used
    manager.record_skill_use(skill.skill_id)

    result = manager.run_lifecycle_maintenance(stale_days=30)

    retrieved = manager.get_skill(skill.skill_id)
    assert retrieved.confidence == SkillConfidence.HIGH  # Not decayed
    assert result["decayed"] == 0


def test_lifecycle_maintenance_skips_deprecated_skills() -> None:
    """Maintenance does not double-process already deprecated skills."""
    manager = MemoryManager()
    old_created = datetime.utcnow() - timedelta(days=60)
    skill = _skill(name="AlreadyDep", confidence=SkillConfidence.LOW, created_at=old_created)
    manager.save_skill(skill)
    manager.deprecate_skill(skill.skill_id)

    result = manager.run_lifecycle_maintenance(stale_days=30)

    assert result["decayed"] == 0


# ---------------------------------------------------------------------------
# Tests: Duplicate Consolidation
# ---------------------------------------------------------------------------


def test_merge_duplicate_skills_combines_stats() -> None:
    manager = MemoryManager()
    primary = _skill(name="Primary", success_count=5, failure_count=1, usage_count=10)
    duplicate = _skill(name="Dup", success_count=3, failure_count=2, usage_count=5, tags=["extra"])
    manager.save_skill(primary)
    manager.save_skill(duplicate)

    ok = manager.merge_duplicate_skills(primary.skill_id, duplicate.skill_id)

    assert ok is True
    skills = manager.list_skills()
    assert len(skills) == 1

    merged = skills[0]
    assert merged.success_count == 8
    assert merged.failure_count == 3
    assert merged.usage_count == 15
    assert "extra" in merged.tags
    assert merged.success_rate == pytest.approx(8 / 11)


def test_merge_keeps_best_confidence() -> None:
    manager = MemoryManager()
    primary = _skill(name="P", confidence=SkillConfidence.MEDIUM)
    dup = _skill(name="D", confidence=SkillConfidence.HIGH)
    manager.save_skill(primary)
    manager.save_skill(dup)

    manager.merge_duplicate_skills(primary.skill_id, dup.skill_id)

    merged = manager.list_skills()[0]
    assert merged.confidence == SkillConfidence.HIGH  # Duplicate's better confidence won


def test_merge_rejects_same_id() -> None:
    manager = MemoryManager()
    skill = _skill(name="Solo")
    manager.save_skill(skill)

    ok = manager.merge_duplicate_skills(skill.skill_id, skill.skill_id)
    assert ok is False


# ---------------------------------------------------------------------------
# Tests: Planner Lifecycle Filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_ignores_deprecated_skills() -> None:
    manager = MemoryManager()
    active_skill = _skill(name="Active One", tags=["gambit"])
    deprecated_skill = _skill(name="Deprecated One", tags=["gambit"])
    manager.save_skill(active_skill)
    manager.save_skill(deprecated_skill)
    manager.deprecate_skill(deprecated_skill.skill_id)

    planner = Planner(memory_manager=manager)
    plan = await planner.plan("I want an Active One.")

    # Deprecated skill must never appear in injected IDs
    assert deprecated_skill.skill_id not in plan.used_skill_ids
    # Active skill may or may not be selected, but deprecated one must not
    assert "Deprecated One" not in plan.used_skill_names


@pytest.mark.asyncio
async def test_planner_ignores_archived_skills() -> None:
    manager = MemoryManager()
    skill = _skill(name="Archived One", tags=["gambit"])
    manager.save_skill(skill)
    manager.archive_skill(skill.skill_id)

    planner = Planner(memory_manager=manager)
    plan = await planner.plan("I want an Archived One.")

    assert skill.skill_id not in plan.used_skill_ids


@pytest.mark.asyncio
async def test_planner_retrieves_active_skills_only() -> None:
    manager = MemoryManager()
    active = _skill(name="Active Skill", tags=["gambit"])
    dep = _skill(name="Deprecated Skill", tags=["gambit"])
    arc = _skill(name="Archived Skill", tags=["gambit"])

    manager.save_skill(active)
    manager.save_skill(dep)
    manager.save_skill(arc)
    manager.deprecate_skill(dep.skill_id)
    manager.archive_skill(arc.skill_id)

    planner = Planner(memory_manager=manager)
    plan = await planner.plan("I want an Active Skill.")

    injected = [t for t in plan.tasks if getattr(t, "origin", None) == "skill_memory"]
    assert all(t.title == "Active Skill" for t in injected)


# ---------------------------------------------------------------------------
# Tests: Lifecycle Metrics
# ---------------------------------------------------------------------------


def test_lifecycle_metrics_counts_states() -> None:
    manager = MemoryManager()
    a = _skill(name="A")
    b = _skill(name="B")
    c = _skill(name="C")
    manager.save_skill(a)
    manager.save_skill(b)
    manager.save_skill(c)
    manager.deprecate_skill(b.skill_id)
    manager.archive_skill(c.skill_id)

    m = manager.get_skill_metrics()
    assert m["active_skills"] == 1
    assert m["deprecated_skills"] == 1
    assert m["archived_skills"] == 1
    assert m["current_skill_count"] == 3


# ---------------------------------------------------------------------------
# Structural Purity
# ---------------------------------------------------------------------------


def test_skill_memory_store_does_not_import_forbidden_modules() -> None:
    """SkillMemoryStore must stay isolated from execution and planning layers."""
    import inspect
    from app.memory import skills as skills_module

    source = inspect.getsource(skills_module)

    forbidden = [
        "ProviderManager",
        "ToolManager",
        "WorkflowEngine",
        "Planner",
        "ReflectionEngine",
        "LearningEngine",
        "CAP",
    ]
    for symbol in forbidden:
        assert symbol not in source, (
            f"SkillMemoryStore must not reference {symbol!r}"
        )
