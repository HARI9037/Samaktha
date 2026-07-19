import pytest

from app.api.execute import execute_request
from app.api.schemas import ExecuteRequest
from app.core.cap import ContextEngine
from app.core.contracts import (
    ExecutionPlan,
    Goal,
    GoalComplexity,
    RoutingDecision,
    RuntimeContext,
    RuntimeResult,
    RouterRequest,
)
from app.core.contracts.planning import PlanTask, TaskKind, TaskStatus
from app.core.gambit import Planner
from app.core.orchestrator import SamakthaOrchestrator
from app.router import ModelRouter, ProviderModelRegistration, RouterRegistry
from app.runtime.base import Runtime
from app.workflow import WorkflowEngine


def _plan(task_count: int = 2) -> ExecutionPlan:
    tasks = [
        PlanTask(
            task_id=f"task-{index}",
            title=f"Task {index}",
            kind=TaskKind.EXECUTE_VIA_RUNTIME,
            description=f"Execute task {index}",
            router_request=RouterRequest(
                purpose="text_generation",
                complexity=GoalComplexity.LOW,
                estimated_context_tokens=10,
                requires_local_model=False,
                requires_code=False,
                requires_reasoning=False,
            ),
        )
        for index in range(task_count)
    ]
    return ExecutionPlan(
        plan_id="report-plan",
        goal=Goal(
            goal_id="goal",
            raw_request="report",
            summary="report",
            complexity=GoalComplexity.LOW,
        ),
        tasks=tasks,
        workflow=[],
        router_request=tasks[0].router_request,
    )


class ReportingRuntime(Runtime):
    def __init__(self, fail_task: str | None = None):
        self.fail_task = fail_task

    async def start(self):
        return None

    async def stop(self):
        return None

    async def run(self, context, task, routing):
        if task.task_id == self.fail_task:
            return RuntimeResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                routing=routing,
                error="failed task",
                duration_ms=3,
            )
        return RuntimeResult(
            task_id=task.task_id,
            status=TaskStatus.COMPLETED,
            routing=routing,
            output={"content": task.task_id},
            duration_ms=5,
        )


class StaticRouter:
    async def route(self, request):
        return RoutingDecision(
            provider_id="mock",
            model_id="mock-model",
            reasoning_summary="static",
        )


@pytest.mark.asyncio
async def test_workflow_aggregates_execution_report():
    result = await WorkflowEngine().execute(
        _plan(),
        runtime=ReportingRuntime(),
        router=StaticRouter(),
        context=RuntimeContext(request_id="report-request"),
    )

    assert result.execution_report is not None
    assert result.execution_report.success is True
    assert result.execution_report.completed_tasks == 2
    assert result.execution_report.failed_tasks == 0
    assert len(result.execution_report.results) == 2


@pytest.mark.asyncio
async def test_workflow_report_preserves_partial_failure():
    result = await WorkflowEngine().execute(
        _plan(),
        runtime=ReportingRuntime(fail_task="task-1"),
        router=StaticRouter(),
        context=RuntimeContext(request_id="report-request"),
    )

    assert result.execution_report is not None
    assert result.execution_report.success is False
    assert result.execution_report.completed_tasks == 1
    assert result.execution_report.failed_tasks == 1
    assert result.execution_report.errors == ["failed task"]


@pytest.mark.asyncio
async def test_orchestrator_propagates_workflow_report_to_runtime_result():
    orchestrator = SamakthaOrchestrator(
        context_engine=ContextEngine(),
        planner=Planner(),
        router=ModelRouter(RouterRegistry([
            ProviderModelRegistration(
                provider_id="mock",
                model_id="mock-model",
                capabilities=["text_generation"],
            ),
        ])),
        runtime=ReportingRuntime(),
    )

    result = await orchestrator.run(
        request="hello",
        runtime_context=RuntimeContext(request_id="orchestrator-report"),
    )

    assert result.metadata["execution_report"]["success"] is True
    assert result.metadata["execution_report"]["completed_tasks"] >= 1


@pytest.mark.asyncio
async def test_api_exposes_optional_diagnostics_without_changing_core_fields():
    class Orchestrator:
        async def run(self, request, runtime_context):
            return RuntimeResult(
                task_id="task",
                status=TaskStatus.COMPLETED,
                output={"content": "ok"},
                metadata={
                    "execution_report": {
                        "plan_id": "plan",
                        "success": True,
                        "completed_tasks": 1,
                    }
                },
            )

    response = await execute_request(
        ExecuteRequest(message="hello"),
        orchestrator=Orchestrator(),
    )

    assert response.response == "ok"
    assert response.diagnostics is not None
    assert response.diagnostics.plan_id == "plan"
