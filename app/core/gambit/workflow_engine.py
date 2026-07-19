from __future__ import annotations

from uuid import uuid4

from app.core.contracts.planning import PlanTask, TaskKind, WorkflowStage, WorkflowStep


class WorkflowEngine:
    """Builds staged runtime workflows from decomposed tasks."""

    _stage_by_kind = {
        TaskKind.UNDERSTAND: WorkflowStage.ANALYZE,
        TaskKind.RETRIEVE_CONTEXT: WorkflowStage.PREPARE,
        TaskKind.PLAN: WorkflowStage.PREPARE,
        TaskKind.TRANSFORM: WorkflowStage.ACT,
        TaskKind.EXECUTE_VIA_RUNTIME: WorkflowStage.ACT,
        TaskKind.VERIFY: WorkflowStage.VERIFY,
        TaskKind.REFLECT: WorkflowStage.REFLECT,
    }

    def build(self, tasks: list[PlanTask]) -> list[WorkflowStep]:
        steps: list[WorkflowStep] = []
        for stage in WorkflowStage:
            task_ids = [
                task.task_id
                for task in tasks
                if self._stage_by_kind.get(task.kind) == stage
            ]
            if not task_ids:
                continue
            steps.append(
                WorkflowStep(
                    step_id=f"step-{uuid4()}",
                    stage=stage,
                    title=self._title_for(stage),
                    task_ids=task_ids,
                )
            )
        return steps

    @staticmethod
    def _title_for(stage: WorkflowStage) -> str:
        return {
            WorkflowStage.ANALYZE: "Analyze goal",
            WorkflowStage.PREPARE: "Prepare plan",
            WorkflowStage.ACT: "Package runtime actions",
            WorkflowStage.VERIFY: "Verify plan",
            WorkflowStage.REFLECT: "Reflect on outcome",
        }[stage]
