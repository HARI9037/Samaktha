from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.contracts import ExecutionPlan, RouterRequest, RuntimeContext, RuntimeResult, RuntimeTask
from app.core.contracts.planning import TaskStatus
from app.router.base import Router
from app.runtime.base import Runtime
from app.workflow.models import WorkflowResult, WorkflowTask
from app.workflow.state import WorkflowState


class WorkflowEngine:
    """Sequential workflow executor for an existing execution plan."""

    async def execute(
        self,
        execution_plan: ExecutionPlan,
        runtime: Runtime,
        router: Router,
        context: RuntimeContext | None = None,
    ) -> WorkflowResult:
        runtime_context = context or RuntimeContext(
            request_id=execution_plan.plan_id)
        workflow_tasks = self._workflow_tasks(execution_plan)
        state = WorkflowState(
            workflow_id=execution_plan.plan_id,
            status="running",
            total_steps=len(workflow_tasks),
            started_at=datetime.utcnow(),
        )

        if not workflow_tasks:
            state.status = "failed"
            state.finished_at = datetime.utcnow()
            state.errors.append(
                "No workflow tasks were produced for execution.")
            return WorkflowResult(success=False, workflow_state=state, outputs=[], errors=list(state.errors))

        outputs: list[Any] = []
        for index, workflow_task in enumerate(workflow_tasks, start=1):
            state.current_step = index
            routing_request = self._routing_request_for(
                execution_plan, workflow_task)

            try:
                routing = await router.route(routing_request)
                result = await runtime.run(runtime_context, workflow_task.runtime_task, routing)
            except Exception as exc:  # pragma: no cover - defensive boundary protection
                result = RuntimeResult(
                    task_id=workflow_task.task_id,
                    status=TaskStatus.FAILED,
                    error=str(exc),
                )

            outputs.append(result)
            state.results.append(result)

            if result.status == TaskStatus.COMPLETED:
                state.completed_steps += 1
                continue

            state.failed_step = index
            state.status = "failed"
            if result.error:
                state.errors.append(result.error)
            else:
                state.errors.append(
                    f"Workflow task failed: {workflow_task.task_id}")
            state.finished_at = datetime.utcnow()
            return WorkflowResult(
                success=False,
                workflow_state=state,
                outputs=outputs,
                errors=list(state.errors),
            )

        state.status = "completed"
        state.finished_at = datetime.utcnow()
        return WorkflowResult(success=True, workflow_state=state, outputs=outputs, errors=list(state.errors))

    async def run(
        self,
        execution_plan: ExecutionPlan,
        runtime: Runtime,
        router: Router,
        context: RuntimeContext | None = None,
    ) -> WorkflowResult:
        return await self.execute(execution_plan=execution_plan, runtime=runtime, router=router, context=context)

    @staticmethod
    def _routing_request_for(execution_plan: ExecutionPlan, workflow_task: WorkflowTask) -> RouterRequest:
        router_request = workflow_task.runtime_task.metadata.get(
            "router_request")
        if isinstance(router_request, RouterRequest):
            return router_request
        return execution_plan.router_request

    @staticmethod
    def _workflow_tasks(execution_plan: ExecutionPlan) -> list[WorkflowTask]:
        task_by_id = {task.task_id: task for task in execution_plan.tasks}
        ordered_task_ids: list[str] = []

        if execution_plan.workflow:
            for step in execution_plan.workflow:
                for task_id in step.task_ids:
                    if task_id not in ordered_task_ids:
                        ordered_task_ids.append(task_id)

        if not ordered_task_ids:
            ordered_task_ids = [task.task_id for task in execution_plan.tasks]
        else:
            for task in execution_plan.tasks:
                if task.task_id not in ordered_task_ids:
                    ordered_task_ids.append(task.task_id)

        workflow_tasks: list[WorkflowTask] = []
        for task_id in ordered_task_ids:
            plan_task = task_by_id.get(task_id)
            if plan_task is None:
                continue
            workflow_tasks.append(
                WorkflowTask(
                    task_id=plan_task.task_id,
                    name=plan_task.title,
                    description=plan_task.description,
                    runtime_task=RuntimeTask(
                        task_id=plan_task.task_id,
                        title=plan_task.title,
                        description=plan_task.description,
                        action_type=plan_task.execution_action_type,
                        inputs={
                            "prompt": plan_task.description,
                            "plan_task_id": plan_task.task_id,
                            "plan_task_kind": plan_task.kind.value,
                        },
                        dependencies=plan_task.dependencies,
                        metadata={
                            "plan_id": execution_plan.plan_id,
                            "plan_task_id": plan_task.task_id,
                            "plan_task_kind": plan_task.kind.value,
                            "router_request": plan_task.router_request,
                        },
                    ),
                )
            )
        return workflow_tasks
