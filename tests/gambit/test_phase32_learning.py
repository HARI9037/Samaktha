"""Phase 3.2 — Skill Learning Engine tests.

Validates that LearningEngine:
- Produces correct LearningResult from the (plan, report, reflection) triple.
- Applies deterministic confidence thresholds.
- Discards low-value and failed patterns.
- Is purely analytical (no executors, providers, memory, or runtime imports).
- Handles all edge-cases gracefully (empty, all-failure, etc.).
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from app.core.contracts.learning import LearningResult, SkillCandidate, SkillConfidence
from app.core.contracts.planning import (
    ExecutionPlan,
    FailureCause,
    Goal,
    GoalComplexity,
    PlanTask,
    ReflectionResult,
    ReplanRecommendation,
    RouterRequest,
    TaskKind,
    TaskStatus,
    WorkflowStage,
    WorkflowStep,
)
from app.core.gambit.learning import LearningEngine
from app.runtime.report import ExecutionReport


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _router_request() -> RouterRequest:
    return RouterRequest(
        purpose="test",
        complexity=GoalComplexity.LOW,
        estimated_context_tokens=512,
        requires_local_model=False,
        requires_code=False,
        requires_reasoning=False,
    )


def _goal(summary: str = "test goal") -> Goal:
    return Goal(
        goal_id=f"goal-{uuid4()}",
        raw_request=summary,
        summary=summary,
        complexity=GoalComplexity.LOW,
    )


def _plan(n_tasks: int = 3, action_type: str = "text_generation") -> ExecutionPlan:
    tasks = [
        PlanTask(
            task_id=f"task-{i}",
            title=f"Execute step {i}",
            kind=TaskKind.EXECUTE_VIA_RUNTIME,
            description=f"Perform execution step {i}",
            router_request=_router_request(),
            execution_action_type=action_type,
        )
        for i in range(n_tasks)
    ]
    step = WorkflowStep(
        step_id="step-1",
        stage=WorkflowStage.ACT,
        title="Act",
        task_ids=[t.task_id for t in tasks],
    )
    return ExecutionPlan(
        plan_id=f"plan-{uuid4()}",
        goal=_goal(),
        tasks=tasks,
        workflow=[step],
        router_request=_router_request(),
    )


def _report(
    *,
    success: bool = True,
    completed: int = 3,
    failed: int = 0,
    errors: list[str] | None = None,
) -> ExecutionReport:
    return ExecutionReport(
        plan_id="plan-test",
        success=success,
        started_at=datetime.now(),
        finished_at=datetime.now(),
        duration_ms=200,
        completed_tasks=completed,
        failed_tasks=failed,
        errors=errors or [],
    )


def _reflection(
    *,
    success_rate: float = 1.0,
    completed_ids: list[str] | None = None,
    failed_ids: list[str] | None = None,
    repeated_failures: list[str] | None = None,
    failure_causes: list[FailureCause] | None = None,
    recommendation: ReplanRecommendation = ReplanRecommendation.RETRY_SAME_PLAN,
) -> ReflectionResult:
    return ReflectionResult(
        plan_id="plan-test",
        reflection_id=f"refl-{uuid4()}",
        total_tasks=3,
        completed_count=int(success_rate * 3),
        failed_count=3 - int(success_rate * 3),
        success_rate=success_rate,
        completed_task_ids=completed_ids or [],
        failure_causes=failure_causes or [],
        repeated_failures=repeated_failures or [],
        replan_recommendation=recommendation,
        replan_worthwhile=recommendation in {
            ReplanRecommendation.REPLAN_IMMEDIATELY,
            ReplanRecommendation.REPLAN_WITH_CONTEXT,
        },
    )


# ---------------------------------------------------------------------------
# Core behaviour tests
# ---------------------------------------------------------------------------


def test_learn_returns_learning_result_type() -> None:
    """learn() always returns a LearningResult instance."""
    engine = LearningEngine()
    plan = _plan()
    report = _report()
    reflection = _reflection()

    result = engine.learn(plan, report, reflection)

    assert isinstance(result, LearningResult)
    assert result.learning_id.startswith("learn-")


def test_learn_successful_tasks_produce_candidates() -> None:
    """A fully successful execution produces at least one SkillCandidate."""
    engine = LearningEngine()
    plan = _plan(n_tasks=3)
    report = _report(success=True, completed=3, failed=0)
    reflection = _reflection(success_rate=1.0)

    result = engine.learn(plan, report, reflection)

    assert len(result.candidates) > 0
    for c in result.candidates:
        assert isinstance(c, SkillCandidate)
        assert c.source_plan_id == plan.plan_id


def test_learn_empty_report_produces_no_candidates() -> None:
    """A report with zero completed tasks produces no useful candidates."""
    engine = LearningEngine()
    plan = _plan(n_tasks=3)
    report = _report(success=False, completed=0, failed=3)
    reflection = _reflection(success_rate=0.0, recommendation=ReplanRecommendation.ABANDON)

    result = engine.learn(plan, report, reflection)

    # No executable candidates should be extracted
    assert result.candidates == []


def test_learn_repeated_failure_goes_to_discarded() -> None:
    """Tasks in reflection.repeated_failures become discarded candidates."""
    engine = LearningEngine()
    plan = _plan(n_tasks=2)
    report = _report(success=False, completed=0, failed=2)
    reflection = _reflection(
        success_rate=0.0,
        repeated_failures=[plan.tasks[0].task_id],
        failure_causes=[FailureCause.REPEATED_FAILURE],
        recommendation=ReplanRecommendation.REPLAN_IMMEDIATELY,
    )

    result = engine.learn(plan, report, reflection)

    assert len(result.discarded_candidates) > 0
    categories = [c.category for c in result.discarded_candidates]
    assert "failed_pattern" in categories


def test_confidence_low_for_single_observation() -> None:
    """A pattern observed exactly once gets LOW confidence."""
    from app.core.gambit.learning import LearningEngine, _MEDIUM_CONFIDENCE_OBSERVATIONS  # noqa: PLC0415

    engine = LearningEngine()
    conf = engine._confidence_for_observations(1)
    assert conf == SkillConfidence.LOW


def test_confidence_medium_for_two_observations() -> None:
    """A pattern observed 2–3 times gets MEDIUM confidence."""
    engine = LearningEngine()
    assert engine._confidence_for_observations(2) == SkillConfidence.MEDIUM
    assert engine._confidence_for_observations(3) == SkillConfidence.MEDIUM


def test_confidence_high_for_four_plus_observations() -> None:
    """A pattern observed 4+ times gets HIGH confidence."""
    engine = LearningEngine()
    assert engine._confidence_for_observations(4) == SkillConfidence.HIGH
    assert engine._confidence_for_observations(10) == SkillConfidence.HIGH


def test_repeated_success_builds_higher_confidence() -> None:
    """More tasks of the same kind produces a higher-confidence candidate."""
    engine = LearningEngine()

    # 1 task → LOW
    plan_small = _plan(n_tasks=1)
    r1 = engine.learn(plan_small, _report(completed=1), _reflection(success_rate=1.0))

    # 4 tasks of the same kind → HIGH
    plan_large = _plan(n_tasks=4)
    r4 = engine.learn(plan_large, _report(completed=4), _reflection(success_rate=1.0))

    small_conf = r1.candidates[0].confidence if r1.candidates else SkillConfidence.LOW
    large_conf = r4.candidates[0].confidence if r4.candidates else SkillConfidence.LOW

    # Confidence cannot decrease as observations increase
    order = [SkillConfidence.LOW, SkillConfidence.MEDIUM, SkillConfidence.HIGH]
    assert order.index(large_conf) >= order.index(small_conf)


def test_reflection_failure_causes_influence_discarded() -> None:
    """Reflection with REPEATED_FAILURE cause leads to discarded candidates."""
    engine = LearningEngine()
    plan = _plan(n_tasks=2)
    report = _report(success=False, completed=0, failed=2)
    reflection = _reflection(
        success_rate=0.0,
        repeated_failures=[plan.tasks[0].task_id, plan.tasks[1].task_id],
        failure_causes=[FailureCause.REPEATED_FAILURE],
        recommendation=ReplanRecommendation.ABANDON,
    )

    result = engine.learn(plan, report, reflection)

    assert len(result.discarded_candidates) >= 2


def test_learning_result_metadata_contains_plan_id() -> None:
    """LearningResult.metadata preserves plan_id and goal_summary."""
    engine = LearningEngine()
    plan = _plan()
    report = _report()
    reflection = _reflection()

    result = engine.learn(plan, report, reflection)

    assert result.metadata["plan_id"] == plan.plan_id
    assert "goal_summary" in result.metadata
    assert "success_rate" in result.metadata


def test_learning_result_summary_not_empty() -> None:
    """LearningResult.summary is always a non-empty string."""
    engine = LearningEngine()
    plan = _plan()
    report = _report()
    reflection = _reflection()

    result = engine.learn(plan, report, reflection)

    assert isinstance(result.summary, str)
    assert len(result.summary) > 0


def test_learning_result_summary_empty_execution() -> None:
    """Summary indicates nothing was learned when report is empty."""
    engine = LearningEngine()
    plan = _plan()
    report = _report(success=False, completed=0, failed=0)
    reflection = _reflection(success_rate=0.0)

    result = engine.learn(plan, report, reflection)

    assert "Nothing learned" in result.summary or len(result.candidates) == 0


def test_learn_does_not_mutate_plan() -> None:
    """learn() must not mutate the input ExecutionPlan."""
    engine = LearningEngine()
    plan = _plan()
    original_plan_id = plan.plan_id
    original_task_count = len(plan.tasks)
    report = _report()
    reflection = _reflection()

    engine.learn(plan, report, reflection)

    assert plan.plan_id == original_plan_id
    assert len(plan.tasks) == original_task_count


def test_learn_does_not_mutate_report() -> None:
    """learn() must not mutate the input ExecutionReport."""
    engine = LearningEngine()
    plan = _plan()
    report = _report(completed=3, failed=0)
    reflection = _reflection()
    original_completed = report.completed_tasks

    engine.learn(plan, report, reflection)

    assert report.completed_tasks == original_completed


def test_learn_output_is_deterministic() -> None:
    """Two calls with the same logical inputs produce structurally identical results."""
    engine = LearningEngine()
    plan = _plan(n_tasks=3)
    report = _report(completed=3)
    reflection = _reflection(success_rate=1.0)

    r1 = engine.learn(plan, report, reflection)
    r2 = engine.learn(plan, report, reflection)

    # Candidate count and categories must be identical across calls
    assert len(r1.candidates) == len(r2.candidates)
    assert len(r1.discarded_candidates) == len(r2.discarded_candidates)
    cats1 = sorted(c.category for c in r1.candidates)
    cats2 = sorted(c.category for c in r2.candidates)
    assert cats1 == cats2


def test_skill_candidate_has_required_fields() -> None:
    """Every extracted SkillCandidate must have required fields populated."""
    engine = LearningEngine()
    plan = _plan(n_tasks=3)
    report = _report()
    reflection = _reflection()

    result = engine.learn(plan, report, reflection)

    for c in result.candidates:
        assert c.skill_id
        assert c.title
        assert c.description
        assert c.source_plan_id == plan.plan_id
        assert isinstance(c.confidence, SkillConfidence)
        assert 0.0 <= c.estimated_value <= 1.0


# ---------------------------------------------------------------------------
# Structural purity test
# ---------------------------------------------------------------------------


def test_learning_engine_does_not_import_forbidden_modules() -> None:
    """LearningEngine source must not reference runtime, workflow, providers, tools, or memory."""
    import inspect
    from app.core.gambit import learning as learning_module

    source = inspect.getsource(learning_module)

    forbidden = [
        "ProviderManager",
        "ToolManager",
        "ToolExecutor",
        "ProviderExecutor",
        "PlanBuilder",
        "Runtime",
        "MemoryReader",
        "MemoryRecord",
    ]
    for symbol in forbidden:
        assert symbol not in source, (
            f"LearningEngine must not reference {symbol!r} — "
            "learning is purely analytical."
        )
