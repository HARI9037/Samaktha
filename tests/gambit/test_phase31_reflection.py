"""Phase 3.1 — Reflection Engine tests.

These tests verify that ReflectionEngine:
- Produces correct ReflectionResult from ExecutionReport (new API).
- Preserves full backward compatibility with the legacy reflect() API.
- Is purely analytical: it never instantiates executors, providers, or memory.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from app.core.contracts.planning import (
    ExecutionPlan,
    FailureCause,
    Goal,
    GoalComplexity,
    PlanReflection,
    PlanTask,
    ReflectionResult,
    ReplanRecommendation,
    RouterRequest,
    TaskKind,
    TaskOutcome,
    TaskStatus,
    WorkflowStage,
    WorkflowStep,
)
from app.core.gambit.reflection import ReflectionEngine
from app.runtime.report import ExecutionReport


# ---------------------------------------------------------------------------
# Fixtures
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


def _plan(n_tasks: int = 3) -> ExecutionPlan:
    goal = Goal(
        goal_id=f"goal-{uuid4()}",
        raw_request="test goal",
        summary="Test goal",
        complexity=GoalComplexity.LOW,
    )
    tasks = [
        PlanTask(
            task_id=f"task-{i}",
            title=f"Task {i}",
            kind=TaskKind.EXECUTE_VIA_RUNTIME,
            description=f"Task {i} description",
            router_request=_router_request(),
        )
        for i in range(n_tasks)
    ]
    step = WorkflowStep(
        step_id="step-1",
        stage=WorkflowStage.ACT,
        title="Execute",
        task_ids=[t.task_id for t in tasks],
    )
    return ExecutionPlan(
        plan_id=f"plan-{uuid4()}",
        goal=goal,
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
    results: list | None = None,
) -> ExecutionReport:
    return ExecutionReport(
        plan_id="plan-test",
        success=success,
        started_at=datetime.now(),
        finished_at=datetime.now(),
        duration_ms=100,
        completed_tasks=completed,
        failed_tasks=failed,
        results=results or [],
        errors=errors or [],
    )


# ---------------------------------------------------------------------------
# Phase 3.1 tests — reflect_on_report
# ---------------------------------------------------------------------------


def test_reflect_all_complete() -> None:
    """Full success produces RETRY_SAME_PLAN and replan_worthwhile=False."""
    engine = ReflectionEngine()
    plan = _plan(n_tasks=3)
    report = _report(success=True, completed=3, failed=0)

    result = engine.reflect_on_report(plan, report)

    assert isinstance(result, ReflectionResult)
    assert result.success_rate == 1.0
    assert result.replan_recommendation == ReplanRecommendation.RETRY_SAME_PLAN
    assert result.replan_worthwhile is False
    assert result.failed_count == 0
    assert result.completed_count == 3


def test_reflect_single_failure_recommends_replan() -> None:
    """A single failure with errors produces REPLAN_WITH_CONTEXT and lessons."""
    engine = ReflectionEngine()
    plan = _plan(n_tasks=3)
    report = _report(success=False, completed=2, failed=1, errors=["Something went wrong"])

    result = engine.reflect_on_report(plan, report)

    assert result.replan_worthwhile is True
    assert result.failed_count == 1
    assert len(result.lessons) > 0
    assert len(result.follow_up_tasks) == 1


def test_reflect_all_failed_recommends_abandon() -> None:
    """Zero successful tasks → ABANDON recommendation."""
    engine = ReflectionEngine()
    plan = _plan(n_tasks=3)
    report = _report(success=False, completed=0, failed=3, errors=["total failure"])

    result = engine.reflect_on_report(plan, report)

    assert result.replan_recommendation == ReplanRecommendation.ABANDON
    assert result.success_rate == 0.0
    assert result.replan_worthwhile is False


def test_reflect_policy_block_detection() -> None:
    """Errors containing policy/CAP keywords produce POLICY_BLOCK cause."""
    engine = ReflectionEngine()
    plan = _plan(n_tasks=2)
    report = _report(
        success=False,
        completed=0,
        failed=2,
        errors=["Action blocked by CAP governance policy"],
    )

    result = engine.reflect_on_report(plan, report)

    assert FailureCause.POLICY_BLOCK in result.failure_causes
    assert result.replan_recommendation == ReplanRecommendation.REPLAN_WITH_CONTEXT


def test_reflect_provider_error_detection() -> None:
    """Errors mentioning provider/model produce PROVIDER_ERROR cause."""
    engine = ReflectionEngine()
    plan = _plan(n_tasks=2)
    report = _report(
        success=False,
        completed=1,
        failed=1,
        errors=["Provider timeout: model did not respond"],
    )

    result = engine.reflect_on_report(plan, report)

    assert FailureCause.PROVIDER_ERROR in result.failure_causes


def test_reflect_tool_error_detection() -> None:
    """Errors mentioning tool execution produce TOOL_ERROR cause."""
    engine = ReflectionEngine()
    plan = _plan(n_tasks=2)
    report = _report(
        success=False,
        completed=1,
        failed=1,
        errors=["Tool not found: filesystem_read"],
    )

    result = engine.reflect_on_report(plan, report)

    assert FailureCause.TOOL_ERROR in result.failure_causes


def test_reflect_empty_report_handled_gracefully() -> None:
    """An empty report (no results, no errors) is handled without error."""
    engine = ReflectionEngine()
    plan = _plan(n_tasks=3)
    report = _report(success=True, completed=0, failed=0, errors=[], results=[])

    result = engine.reflect_on_report(plan, report)

    assert isinstance(result, ReflectionResult)
    assert result.total_tasks == 3
    assert result.completed_count == 0


def test_reflect_on_report_returns_reflection_result_type() -> None:
    """reflect_on_report always returns a ReflectionResult instance."""
    engine = ReflectionEngine()
    plan = _plan()
    report = _report()

    result = engine.reflect_on_report(plan, report)

    assert type(result).__name__ == "ReflectionResult"
    assert hasattr(result, "reflection_id")
    assert result.reflection_id.startswith("refl-")


def test_reflect_follow_up_tasks_generated_per_error() -> None:
    """One follow-up PlanTask is generated for every reported error."""
    engine = ReflectionEngine()
    plan = _plan(n_tasks=2)
    report = _report(
        success=False,
        completed=0,
        failed=2,
        errors=["Error A", "Error B"],
    )

    result = engine.reflect_on_report(plan, report)

    assert len(result.follow_up_tasks) == 2
    for fu in result.follow_up_tasks:
        assert isinstance(fu, PlanTask)
        assert fu.kind == TaskKind.PLAN
        assert fu.cap_required is True


def test_reflect_duration_propagated() -> None:
    """duration_ms from the report is propagated to ReflectionResult."""
    engine = ReflectionEngine()
    plan = _plan()
    report = _report()
    report = ExecutionReport(
        plan_id="plan-dur",
        success=True,
        duration_ms=4200,
        completed_tasks=3,
        failed_tasks=0,
    )

    result = engine.reflect_on_report(plan, report)

    assert result.duration_ms == 4200


# ---------------------------------------------------------------------------
# Backward compatibility tests — legacy reflect()
# ---------------------------------------------------------------------------


def test_reflect_backward_compat_success() -> None:
    """Legacy reflect() method still returns PlanReflection unchanged."""
    engine = ReflectionEngine()
    plan = _plan(n_tasks=2)
    outcomes = [
        TaskOutcome(task_id="task-0", status=TaskStatus.COMPLETED, summary="OK"),
        TaskOutcome(task_id="task-1", status=TaskStatus.COMPLETED, summary="OK"),
    ]

    result = engine.reflect(plan, outcomes)

    assert isinstance(result, PlanReflection)
    assert result.plan_id == plan.plan_id
    assert len(result.completed_task_ids) == 2
    assert len(result.failed_task_ids) == 0


def test_reflect_backward_compat_with_failure() -> None:
    """Legacy reflect() method correctly surfaces failed and blocked tasks."""
    engine = ReflectionEngine()
    plan = _plan(n_tasks=3)
    outcomes = [
        TaskOutcome(task_id="task-0", status=TaskStatus.COMPLETED, summary="OK"),
        TaskOutcome(task_id="task-1", status=TaskStatus.FAILED, summary="Provider error"),
        TaskOutcome(task_id="task-2", status=TaskStatus.BLOCKED, summary="Waiting on CAP"),
    ]

    result = engine.reflect(plan, outcomes)

    assert isinstance(result, PlanReflection)
    assert "task-1" in result.failed_task_ids
    assert "task-2" in result.blocked_task_ids
    assert len(result.follow_up_tasks) == 2
    assert len(result.lessons) > 0


def test_reflect_backward_compat_empty_outcomes() -> None:
    """Legacy reflect() with no outcomes returns a graceful PlanReflection."""
    engine = ReflectionEngine()
    plan = _plan(n_tasks=2)

    result = engine.reflect(plan, [])

    assert isinstance(result, PlanReflection)
    assert "No runtime outcomes were reported." in result.lessons


# ---------------------------------------------------------------------------
# Structural test — ReflectionEngine is purely analytical
# ---------------------------------------------------------------------------


def test_reflect_does_not_instantiate_executors() -> None:
    """ReflectionEngine source must not reference executor, provider, or memory types."""
    import inspect
    from app.core.gambit import reflection as reflection_module

    source = inspect.getsource(reflection_module)

    forbidden = [
        "ProviderManager",
        "ToolManager",
        "MemoryManager",
        "ToolExecutor",
        "ProviderExecutor",
        "MemoryReader",
    ]
    for symbol in forbidden:
        assert symbol not in source, (
            f"ReflectionEngine must not reference {symbol!r} — "
            "reflection is purely analytical."
        )
