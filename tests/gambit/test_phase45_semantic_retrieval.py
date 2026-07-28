"""Phase 4.5 tests — Planner uses MemoryManager for semantic skill retrieval.

Ensures:
- Planner receives semantically ranked skills from MemoryManager
- Planner does NOT import SemanticIndex or ContextMemoryStore directly
- MemoryManager store_memory / search_memory APIs work end-to-end
- Architecture: GAMBIT accesses Memory only via MemoryManager interface
"""
from __future__ import annotations

import inspect
import pytest

from app.core.contracts.learning import SkillConfidence
from app.core.contracts.memory import MemoryItem, MemoryType
from app.core.contracts.skills import SkillRecord
from app.memory.manager import MemoryManager


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def memory() -> MemoryManager:
    return MemoryManager()


@pytest.fixture
def skill_memory(memory: MemoryManager) -> MemoryManager:
    """Populate with semantically distinct skills."""
    memory.save_skill(SkillRecord(
        skill_id="s-exec",
        name="Parallel Execution Orchestrator",
        description="Orchestrates parallel task execution across workflow stages",
        category="execution",
        confidence=SkillConfidence.HIGH,
        source_plan="p1",
        tags=["parallel", "workflow", "execution"],
    ))
    memory.save_skill(SkillRecord(
        skill_id="s-data",
        name="Data Transformation Pipeline",
        description="Transforms raw data through ETL pipeline stages",
        category="data",
        confidence=SkillConfidence.MEDIUM,
        source_plan="p2",
        tags=["data", "etl", "transform"],
    ))
    memory.save_skill(SkillRecord(
        skill_id="s-ml",
        name="Machine Learning Model Trainer",
        description="Trains and evaluates machine learning classification models",
        category="ml",
        confidence=SkillConfidence.HIGH,
        source_plan="p3",
        tags=["ml", "model", "training", "classification"],
    ))
    return memory


# ------------------------------------------------------------------
# Semantic retrieval via MemoryManager
# ------------------------------------------------------------------

def test_find_relevant_skills_semantic_ranking(skill_memory: MemoryManager):
    """Semantic query should rank execution-related skill highest for execution goal."""
    results = skill_memory.find_relevant_skills("orchestrate parallel workflow execution")
    assert len(results) >= 1
    # The execution skill should rank first due to token overlap
    assert results[0].skill.skill_id == "s-exec"


def test_find_relevant_skills_ml_goal(skill_memory: MemoryManager):
    """ML goal should retrieve ML skill."""
    results = skill_memory.find_relevant_skills("train machine learning classification model")
    assert len(results) >= 1
    top_ids = [r.skill.skill_id for r in results[:2]]
    assert "s-ml" in top_ids


def test_find_relevant_skills_data_goal(skill_memory: MemoryManager):
    """ETL goal should surface data skill."""
    results = skill_memory.find_relevant_skills("transform data ETL pipeline")
    assert len(results) >= 1
    assert results[0].skill.skill_id == "s-data"


# ------------------------------------------------------------------
# store_memory / search_memory round-trip
# ------------------------------------------------------------------

def test_store_and_search_memory(memory: MemoryManager):
    item = MemoryItem(
        content="workflow execution succeeded with 3 parallel tasks",
        category=MemoryType.EXECUTION,
        metadata={"plan_id": "plan-abc"},
    )
    memory.store_memory(item)

    results = memory.search_memory("parallel workflow execution")
    assert len(results) >= 1
    assert results[0].item.id == item.id


def test_search_memory_type_filter(memory: MemoryManager):
    memory.store_memory(MemoryItem(content="python skill automation task", category=MemoryType.SKILL))
    memory.store_memory(MemoryItem(content="python execution failure retry", category=MemoryType.FAILURE_PATTERN))

    skill_results = memory.search_memory("python", memory_type=MemoryType.SKILL)
    assert all(r.item.category == MemoryType.SKILL for r in skill_results)


def test_delete_and_update_memory(memory: MemoryManager):
    item = MemoryItem(content="initial context content execution", category=MemoryType.CONTEXT)
    memory.store_memory(item)

    # Update
    item.content = "updated workflow execution context with retry"
    memory.update_memory(item)
    results = memory.search_memory("retry workflow")
    assert len(results) >= 1

    # Delete
    memory.delete_memory(item.id)
    results_after = memory.search_memory("retry workflow")
    assert all(r.item.id != item.id for r in results_after)


def test_get_recent_context(memory: MemoryManager):
    import time
    for i in range(5):
        memory.store_memory(MemoryItem(content=f"context execution step {i}", category=MemoryType.EXECUTION))
        time.sleep(0.001)

    recent = memory.get_recent_context(n=3)
    assert len(recent) == 3


# ------------------------------------------------------------------
# Architecture checks
# ------------------------------------------------------------------

def test_planner_does_not_import_semantic_index():
    """GAMBIT Planner must not directly import SemanticIndex or ContextMemoryStore."""
    import app.core.gambit.planner as planner_mod
    src = inspect.getsource(planner_mod)
    assert "SemanticIndex" not in src
    assert "ContextMemoryStore" not in src
    assert "semantic_index" not in src


def test_memory_manager_does_not_import_runtime():
    """Memory must not import Runtime."""
    import app.memory.manager as mgr_mod
    src = inspect.getsource(mgr_mod)
    assert "app.runtime" not in src
    assert "app.workflow" not in src


def test_memory_manager_does_not_import_gambit():
    """Memory must not import GAMBIT."""
    import app.memory.manager as mgr_mod
    src = inspect.getsource(mgr_mod)
    assert "app.core.gambit" not in src
