"""Phase 3.4 — Planner Skill Retrieval Tests.

Validates deterministic retrieval and injection of skills into ExecutionPlans.
Ensures Planner remains structurally pure and does not leak execution concerns.
"""
from __future__ import annotations

import pytest

from app.core.contracts.learning import SkillConfidence
from app.core.contracts.skills import SkillLifecycleState, SkillRecord
from app.core.gambit.planner import Planner
from app.memory.manager import MemoryManager


@pytest.fixture
def populated_memory() -> MemoryManager:
    manager = MemoryManager()
    
    # 1. High confidence, high success rate skill
    s1 = SkillRecord(
        skill_id="s1",
        name="High Quality Extract",
        description="Extracts data reliably",
        category="general",
        confidence=SkillConfidence.HIGH,
        source_plan="plan-x",
        usage_count=10,
        success_count=10,
        failure_count=0,
        tags=["gambit"]
    )
    manager.save_skill(s1)

    # 2. Medium confidence, decent success rate
    s2 = SkillRecord(
        skill_id="s2",
        name="Medium Quality Extract",
        description="Extracts data okay",
        category="general",
        confidence=SkillConfidence.MEDIUM,
        source_plan="plan-x",
        usage_count=5,
        success_count=4,
        failure_count=1,
        tags=["gambit"]
    )
    manager.save_skill(s2)

    # 3. Low confidence (should be ignored)
    s3 = SkillRecord(
        skill_id="s3",
        name="Low Quality Extract",
        description="Fails often",
        category="general",
        confidence=SkillConfidence.LOW,
        source_plan="plan-x",
        usage_count=2,
        success_count=0,
        failure_count=2,
        tags=["gambit"]
    )
    manager.save_skill(s3)

    # 4. High confidence, but deprecated (via lifecycle_state, not tags)
    s4 = SkillRecord(
        skill_id="s4",
        name="Deprecated Extract",
        description="Used to work",
        category="general",
        confidence=SkillConfidence.HIGH,
        source_plan="plan-x",
        usage_count=20,
        success_count=20,
        failure_count=0,
        success_rate=1.0,
        lifecycle_state=SkillLifecycleState.DEPRECATED,
        tags=["gambit"]
    )
    manager.save_skill(s4)

    # 5. Another High confidence skill to hit the limit
    s5 = SkillRecord(
        skill_id="s5",
        name="Another High Extract",
        description="Also good",
        category="general",
        confidence=SkillConfidence.HIGH,
        source_plan="plan-x",
        usage_count=5,
        success_count=5,
        failure_count=0,
        tags=["gambit"]
    )
    manager.save_skill(s5)

    # 6. Yet another High confidence skill (should be excluded due to limit=3)
    s6 = SkillRecord(
        skill_id="s6",
        name="Excluded High Extract",
        description="Also good but late",
        category="general",
        confidence=SkillConfidence.HIGH,
        source_plan="plan-x",
        usage_count=1,
        success_count=1,
        failure_count=0,
        tags=["gambit"]
    )
    manager.save_skill(s6)

    return manager


@pytest.mark.asyncio
async def test_planner_retrieves_and_injects_skills(populated_memory: MemoryManager) -> None:
    planner = Planner(memory_manager=populated_memory)
    plan = await planner.plan("I want to extract data.")

    # Should have injected tasks at the beginning
    assert len(plan.used_skill_ids) > 0
    assert "High Quality Extract" in plan.used_skill_names
    assert len(plan.planner_reasoning) > 0

    injected = [t for t in plan.tasks if getattr(t, "origin", None) == "skill_memory"]
    assert len(injected) == 3  # Limit is 3


@pytest.mark.asyncio
async def test_planner_ignores_low_confidence_and_deprecated(populated_memory: MemoryManager) -> None:
    planner = Planner(memory_manager=populated_memory)
    # Query specifically targets the bad skills so they score highest and get evaluated
    plan = await planner.plan("I want a Low Quality Extract and a Deprecated Extract.")

    # Both bad skills must never appear in the injection results
    assert "s3" not in plan.used_skill_ids  # Rejected: low confidence
    assert "s4" not in plan.used_skill_ids  # Rejected: deprecated (lifecycle_state filter)


@pytest.mark.asyncio
async def test_planner_works_without_memory() -> None:
    planner = Planner()
    plan = await planner.plan("I want to extract data.")

    assert len(plan.used_skill_ids) == 0
    assert len(plan.used_skill_names) == 0
    injected = [t for t in plan.tasks if getattr(t, "origin", None) == "skill_memory"]
    assert len(injected) == 0

    assert "No memory manager provided" in plan.planner_reasoning[0]


def test_planner_does_not_import_forbidden_modules() -> None:
    """Planner must remain structurally pure and isolated from runtime."""
    import inspect
    from app.core.gambit import planner as planner_module

    source = inspect.getsource(planner_module)

    forbidden = [
        "ProviderManager",
        "ToolManager",
        "ToolExecutor",
        "ProviderExecutor",
        "Runtime",
        "PlanBuilder.execute",  # It uses PlanBuilder for build, but not execute
    ]
    for symbol in forbidden:
        assert symbol not in source, (
            f"Planner must not reference {symbol!r} — "
            "it is purely for deterministic planning."
        )
