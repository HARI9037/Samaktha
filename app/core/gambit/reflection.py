from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from app.core.contracts.planning import (
    ExecutionPlan,
    FailureCause,
    PlanReflection,
    PlanTask,
    ReflectionResult,
    ReplanRecommendation,
    TaskKind,
    TaskOutcome,
    TaskStatus,
)

if TYPE_CHECKING:
    # ExecutionReport lives in the runtime domain.  We import it only for type
    # annotations so that contracts never gain a hard dependency on runtime.
    from app.runtime.report import ExecutionReport


# Policy/governance-related keywords used for failure cause detection.
_POLICY_KEYWORDS = frozenset({"cap", "policy", "blocked", "denied", "forbidden", "governance"})
_PROVIDER_KEYWORDS = frozenset({"provider", "timeout", "rate limit", "unavailable", "api error", "model"})
_TOOL_KEYWORDS = frozenset({"tool", "tool not found", "tool error", "tool failed", "executor"})


class ReflectionEngine:
    """Reflects on runtime-reported outcomes without executing recovery steps.

    Two entrypoints are available:

    * ``reflect_on_report(plan, report)`` — Phase 3.1 primary API.  Accepts the
      rich ``ExecutionReport`` produced by the Workflow engine and returns a
      ``ReflectionResult`` with failure-cause detection, replan recommendations,
      and structured lessons.

    * ``reflect(plan, outcomes)`` — Phase 2 legacy API preserved for full
      backward compatibility.  Returns the lighter ``PlanReflection`` model.
    """

    # ------------------------------------------------------------------
    # Phase 3.1 – primary entrypoint
    # ------------------------------------------------------------------

    def reflect_on_report(
        self,
        plan: ExecutionPlan,
        report: "ExecutionReport",
    ) -> ReflectionResult:
        """Analyse an ``ExecutionReport`` and return a ``ReflectionResult``.

        This method is purely analytical.  It never executes tools, never calls
        providers, and never accesses Memory.
        """
        total = len(plan.tasks)
        completed = report.completed_tasks
        failed = report.failed_tasks
        blocked = total - completed - failed  # remaining tasks not reported as either
        blocked = max(blocked, 0)

        success_rate = (completed / total) if total > 0 else 0.0

        failure_causes = self._detect_failure_causes(report.results, report.errors)
        repeated_failures = self._detect_repeated_failures(report.results)

        if repeated_failures and FailureCause.REPEATED_FAILURE not in failure_causes:
            failure_causes.append(FailureCause.REPEATED_FAILURE)

        recommendation = self._recommend_replan(failure_causes, repeated_failures, success_rate)
        replan_worthwhile = self._is_replan_worthwhile(recommendation)
        lessons = self._generate_lessons(report, failure_causes, success_rate, total)
        follow_ups = self._follow_up_tasks_from_report(plan, report)

        return ReflectionResult(
            plan_id=plan.plan_id,
            reflection_id=f"refl-{uuid4()}",
            total_tasks=total,
            completed_count=completed,
            failed_count=failed,
            blocked_count=blocked,
            success_rate=round(success_rate, 4),
            failure_causes=failure_causes,
            repeated_failures=repeated_failures,
            replan_recommendation=recommendation,
            replan_worthwhile=replan_worthwhile,
            lessons=lessons,
            follow_up_tasks=follow_ups,
            duration_ms=report.duration_ms,
        )

    # ------------------------------------------------------------------
    # Phase 2 – legacy entrypoint (unchanged, preserved for compat)
    # ------------------------------------------------------------------

    def reflect(
        self,
        plan: ExecutionPlan,
        outcomes: list[TaskOutcome],
    ) -> PlanReflection:
        completed = [
            outcome.task_id
            for outcome in outcomes
            if outcome.status == TaskStatus.COMPLETED
        ]
        failed = [
            outcome.task_id
            for outcome in outcomes
            if outcome.status == TaskStatus.FAILED
        ]
        blocked = [
            outcome.task_id
            for outcome in outcomes
            if outcome.status == TaskStatus.BLOCKED
        ]
        lessons = self._lessons(plan, outcomes)
        follow_ups = self._follow_ups(plan, outcomes)

        return PlanReflection(
            plan_id=plan.plan_id,
            completed_task_ids=completed,
            failed_task_ids=failed,
            blocked_task_ids=blocked,
            lessons=lessons,
            follow_up_tasks=follow_ups,
        )

    # ------------------------------------------------------------------
    # Private helpers – Phase 3.1
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_failure_causes(
        results: list[Any],
        errors: list[str],
    ) -> list[FailureCause]:
        """Inspect results and error strings to classify root causes."""
        causes: list[FailureCause] = []
        combined_errors = " ".join(str(e).lower() for e in errors)

        if any(kw in combined_errors for kw in _POLICY_KEYWORDS):
            causes.append(FailureCause.POLICY_BLOCK)
        if any(kw in combined_errors for kw in _PROVIDER_KEYWORDS):
            causes.append(FailureCause.PROVIDER_ERROR)
        if any(kw in combined_errors for kw in _TOOL_KEYWORDS):
            causes.append(FailureCause.TOOL_ERROR)

        # Detect partial output: results present but report flagged failure
        if results and errors:
            causes.append(FailureCause.PARTIAL_OUTPUT)

        if not causes and errors:
            causes.append(FailureCause.UNKNOWN)

        return causes

    @staticmethod
    def _detect_repeated_failures(results: list[Any]) -> list[str]:
        """Return task IDs that appear as failed more than once in results."""
        seen: dict[str, int] = {}
        for result in results:
            task_id = getattr(result, "task_id", None)
            status = getattr(result, "status", None)
            if task_id and str(status) in {"failed", TaskStatus.FAILED}:
                seen[task_id] = seen.get(task_id, 0) + 1
        return [tid for tid, count in seen.items() if count > 1]

    @staticmethod
    def _recommend_replan(
        failure_causes: list[FailureCause],
        repeated_failures: list[str],
        success_rate: float,
    ) -> ReplanRecommendation:
        """Apply deterministic rules to choose a replanning strategy."""
        # Policy blocks always require context gathering, even if nothing succeeded.
        if FailureCause.POLICY_BLOCK in failure_causes:
            return ReplanRecommendation.REPLAN_WITH_CONTEXT

        if success_rate == 0.0:
            return ReplanRecommendation.ABANDON

        if repeated_failures or FailureCause.REPEATED_FAILURE in failure_causes:
            return ReplanRecommendation.REPLAN_IMMEDIATELY

        if failure_causes and success_rate < 0.5:
            return ReplanRecommendation.REPLAN_IMMEDIATELY

        if failure_causes:
            return ReplanRecommendation.REPLAN_WITH_CONTEXT

        return ReplanRecommendation.RETRY_SAME_PLAN

    @staticmethod
    def _is_replan_worthwhile(recommendation: ReplanRecommendation) -> bool:
        return recommendation in {
            ReplanRecommendation.REPLAN_IMMEDIATELY,
            ReplanRecommendation.REPLAN_WITH_CONTEXT,
        }

    @staticmethod
    def _generate_lessons(
        report: "ExecutionReport",
        failure_causes: list[FailureCause],
        success_rate: float,
        total_tasks: int,
    ) -> list[str]:
        lessons: list[str] = []

        if not report.errors and report.success:
            lessons.append("Plan completed successfully with no reported errors.")
            return lessons

        if success_rate == 0.0:
            lessons.append("All tasks failed. Manual review is required before replanning.")

        if FailureCause.POLICY_BLOCK in failure_causes:
            lessons.append(
                "One or more tasks were blocked by the CAP governance layer. "
                "Review permissions and privacy constraints before replanning."
            )
        if FailureCause.PROVIDER_ERROR in failure_causes:
            lessons.append(
                "Provider errors were detected. Consider routing to a different "
                "model or retrying with a reduced context window."
            )
        if FailureCause.TOOL_ERROR in failure_causes:
            lessons.append(
                "Tool execution failures occurred. Verify tool registration and "
                "input argument schema before replanning."
            )
        if FailureCause.PARTIAL_OUTPUT in failure_causes:
            lessons.append(
                "Execution produced partial results. "
                "Some tasks may need to be decomposed further."
            )
        if FailureCause.REPEATED_FAILURE in failure_causes:
            lessons.append(
                "Repeated failures detected for the same tasks. "
                "Task decomposition or goal clarification is recommended."
            )
        if FailureCause.UNKNOWN in failure_causes:
            lessons.append("Failure cause is unclassified. Inspect execution trace for details.")

        if report.completed_tasks < total_tasks and report.completed_tasks > 0:
            lessons.append(
                f"Plan partially completed: {report.completed_tasks}/{total_tasks} tasks succeeded."
            )

        if not lessons:
            lessons.append("Execution finished with errors but root cause is undetermined.")

        return lessons

    @staticmethod
    def _follow_up_tasks_from_report(
        plan: ExecutionPlan,
        report: "ExecutionReport",
    ) -> list[PlanTask]:
        """Generate follow-up PlanTasks for each error captured in the report."""
        if not report.errors:
            return []

        follow_ups: list[PlanTask] = []
        for idx, error_msg in enumerate(report.errors):
            follow_ups.append(
                PlanTask(
                    task_id=f"follow-up-{plan.plan_id}-{idx}",
                    title="Replan: address reported failure",
                    kind=TaskKind.PLAN,
                    description=(
                        f"Review runtime failure and produce a revised plan. "
                        f"Reported error: {error_msg}"
                    ),
                    dependencies=[],
                    suggested_skills=[],
                    router_request=plan.router_request,
                    cap_required=True,
                    status=TaskStatus.PENDING,
                )
            )
        return follow_ups

    # ------------------------------------------------------------------
    # Private helpers – Phase 2 legacy (unchanged)
    # ------------------------------------------------------------------

    @staticmethod
    def _lessons(plan: ExecutionPlan, outcomes: list[TaskOutcome]) -> list[str]:
        lessons = []
        if not outcomes:
            return ["No runtime outcomes were reported."]
        if any(outcome.status == TaskStatus.FAILED for outcome in outcomes):
            lessons.append("At least one task failed and should be replanned before retry.")
        if any(outcome.status == TaskStatus.BLOCKED for outcome in outcomes):
            lessons.append("At least one task is blocked and requires clarification or permission.")
        if len(outcomes) < len(plan.tasks):
            lessons.append("Runtime reported only a partial plan outcome.")
        if not lessons:
            lessons.append("Plan completed without reported failures.")
        return lessons

    @staticmethod
    def _follow_ups(
        plan: ExecutionPlan,
        outcomes: list[TaskOutcome],
    ) -> list[PlanTask]:
        outcome_by_task = {outcome.task_id: outcome for outcome in outcomes}
        follow_ups = []
        for task in plan.tasks:
            outcome = outcome_by_task.get(task.task_id)
            if outcome is None or outcome.status not in {TaskStatus.FAILED, TaskStatus.BLOCKED}:
                continue
            follow_ups.append(
                PlanTask(
                    task_id=f"{task.task_id}-follow-up",
                    title=f"Replan: {task.title}",
                    kind=TaskKind.PLAN,
                    description=f"Review runtime outcome and produce a safer next plan. Outcome: {outcome.summary}",
                    dependencies=[],
                    suggested_skills=task.suggested_skills,
                    router_request=task.router_request,
                    cap_required=True,
                    status=TaskStatus.PENDING,
                )
            )
        return follow_ups
