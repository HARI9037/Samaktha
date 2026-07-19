from __future__ import annotations

from app.core.contracts.planning import (
    ExecutionPlan,
    PlanReflection,
    PlanTask,
    TaskKind,
    TaskOutcome,
    TaskStatus,
)


class ReflectionEngine:
    """Reflects on runtime-reported outcomes without executing recovery steps."""

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
