import asyncio

from app.core.cap import ContextEngine
from app.core.contracts import ExecutionPlan, Goal, RouterRequest, RuntimeContext, RuntimeResult, RuntimeTask, RoutingDecision
from app.core.contracts.planning import GoalComplexity, PlanTask, TaskKind, TaskStatus, WorkflowStage, WorkflowStep
from app.core.gambit import Planner
from app.core.orchestrator import SamakthaOrchestrator
from app.providers.manager import ProviderManager
from app.providers.mock import MockProvider
from app.providers.models import ProviderInfo
from app.providers.registry import ProviderRegistry
from app.router import ModelRouter, ProviderModelRegistration, RouterRegistry
from app.router.base import Router
from app.runtime import ProviderExecutor, RuntimeDispatcher, RuntimeEngine, RuntimeRegistry, ToolExecutor
from app.runtime.base import Runtime
from app.tools import ToolManager, ToolRegistry
from app.workflow import WorkflowEngine


def build_plan(task_count: int = 1) -> ExecutionPlan:
    tasks: list[PlanTask] = []
    steps: list[WorkflowStep] = []

    for index in range(task_count):
        router_request = RouterRequest(
            purpose=f"step-{index + 1}",
            complexity=GoalComplexity.LOW,
            estimated_context_tokens=100,
            requires_local_model=False,
            requires_code=False,
            requires_reasoning=False,
        )
        task = PlanTask(
            task_id=f"task-{index + 1}",
            title=f"Task {index + 1}",
            kind=TaskKind.EXECUTE_VIA_RUNTIME,
            description=f"Execute step {index + 1}",
            router_request=router_request,
        )
        tasks.append(task)
        steps.append(
            WorkflowStep(
                step_id=f"step-{index + 1}",
                stage=WorkflowStage.ACT,
                title=task.title,
                task_ids=[task.task_id],
            )
        )

    return ExecutionPlan(
        plan_id="plan-1",
        goal=Goal(
            goal_id="goal-1",
            raw_request="test request",
            summary="test request",
            complexity=GoalComplexity.LOW,
        ),
        tasks=tasks,
        workflow=steps,
        router_request=tasks[0].router_request,
    )


class RecordingRouter(Router):
    def __init__(self) -> None:
        self.requests: list[RouterRequest] = []

    async def route(self, request: RouterRequest) -> RoutingDecision:
        self.requests.append(request)
        return RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="selected")


class RecordingRuntime(Runtime):
    def __init__(self, fail_on_task_id: str | None = None) -> None:
        self.fail_on_task_id = fail_on_task_id
        self.calls: list[str] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def run(self, context: RuntimeContext, task: RuntimeTask, routing: RoutingDecision) -> RuntimeResult:
        self.calls.append(task.task_id)
        if task.task_id == self.fail_on_task_id:
            return RuntimeResult(task_id=task.task_id, status=TaskStatus.FAILED, routing=routing, error="forced failure")
        return RuntimeResult(task_id=task.task_id, status=TaskStatus.COMPLETED, routing=routing, output={"task_id": task.task_id})


def test_workflow_with_one_task() -> None:
    async def run_test() -> None:
        plan = build_plan(1)
        engine = WorkflowEngine()
        router = RecordingRouter()
        runtime = RecordingRuntime()

        result = await engine.execute(plan, runtime=runtime, router=router, context=RuntimeContext(request_id="req-1"))

        assert result.success is True
        assert result.workflow_state.completed_steps == 1
        assert result.workflow_state.failed_step is None
        assert runtime.calls == ["task-1"]
        assert len(result.outputs) == 1

    asyncio.run(run_test())


def test_workflow_with_multiple_tasks() -> None:
    async def run_test() -> None:
        plan = build_plan(3)
        engine = WorkflowEngine()
        router = RecordingRouter()
        runtime = RecordingRuntime()

        result = await engine.execute(plan, runtime=runtime, router=router, context=RuntimeContext(request_id="req-2"))

        assert result.success is True
        assert runtime.calls == ["task-1", "task-2", "task-3"]
        assert result.workflow_state.total_steps == 3
        assert result.workflow_state.completed_steps == 3
        assert result.workflow_state.current_step == 3

    asyncio.run(run_test())


def test_workflow_stops_on_failure() -> None:
    async def run_test() -> None:
        plan = build_plan(3)
        engine = WorkflowEngine()
        router = RecordingRouter()
        runtime = RecordingRuntime(fail_on_task_id="task-2")

        result = await engine.execute(plan, runtime=runtime, router=router, context=RuntimeContext(request_id="req-3"))

        assert result.success is False
        assert runtime.calls == ["task-1", "task-2"]
        assert result.workflow_state.failed_step == 2
        assert result.workflow_state.completed_steps == 1
        assert result.errors == ["forced failure"]

    asyncio.run(run_test())


def test_workflow_returns_partial_progress() -> None:
    async def run_test() -> None:
        plan = build_plan(3)
        engine = WorkflowEngine()
        router = RecordingRouter()
        runtime = RecordingRuntime(fail_on_task_id="task-2")

        result = await engine.execute(plan, runtime=runtime, router=router, context=RuntimeContext(request_id="req-4"))

        assert len(result.outputs) == 2
        assert result.workflow_state.results[0].task_id == "task-1"
        assert result.workflow_state.results[1].task_id == "task-2"

    asyncio.run(run_test())


def test_workflow_state_updates_correctly() -> None:
    async def run_test() -> None:
        plan = build_plan(2)
        engine = WorkflowEngine()
        router = RecordingRouter()
        runtime = RecordingRuntime()

        result = await engine.execute(plan, runtime=runtime, router=router, context=RuntimeContext(request_id="req-5"))

        assert result.workflow_state.workflow_id == "plan-1"
        assert result.workflow_state.status == "completed"
        assert result.workflow_state.started_at is not None
        assert result.workflow_state.finished_at is not None
        assert result.workflow_state.current_step == 2
        assert result.workflow_state.completed_steps == 2

    asyncio.run(run_test())


def test_orchestrator_uses_workflow_engine() -> None:
    async def run_test() -> None:
        class TrackingWorkflowEngine(WorkflowEngine):
            def __init__(self) -> None:
                self.called = False

            async def execute(self, execution_plan, runtime, router, context=None):
                self.called = True
                return await super().execute(execution_plan, runtime=runtime, router=router, context=context)

        provider_registry = ProviderRegistry()
        provider_registry.register("mock", MockProvider(), ProviderInfo(
            provider_id="mock", capabilities=["text_generation"], models=["mock-model"]))
        provider_manager = ProviderManager(provider_registry)

        runtime_registry = RuntimeRegistry()
        runtime_registry.register(
            "provider", ProviderExecutor(provider_manager))
        runtime_registry.register(
            "tool", ToolExecutor(ToolManager(ToolRegistry())))
        runtime = RuntimeEngine(RuntimeDispatcher(runtime_registry))

        router = ModelRouter(
            RouterRegistry(
                [ProviderModelRegistration(
                    provider_id="mock", model_id="mock-model", capabilities=["text_generation"])]
            )
        )
        workflow_engine = TrackingWorkflowEngine()
        orchestrator = SamakthaOrchestrator(
            context_engine=ContextEngine(),
            planner=Planner(),
            router=router,
            runtime=runtime,
            workflow_engine=workflow_engine,
        )

        result = await orchestrator.run(
            request="hello",
            runtime_context=RuntimeContext(request_id="req-6"),
        )

        assert workflow_engine.called is True
        assert result.status == TaskStatus.COMPLETED

    asyncio.run(run_test())


def test_runtime_unchanged() -> None:
    async def run_test() -> None:
        provider_registry = ProviderRegistry()
        provider_registry.register("mock", MockProvider(), ProviderInfo(
            provider_id="mock", capabilities=["text_generation"], models=["mock-model"]))
        provider_manager = ProviderManager(provider_registry)

        runtime_registry = RuntimeRegistry()
        runtime_registry.register(
            "provider", ProviderExecutor(provider_manager))
        runtime = RuntimeEngine(RuntimeDispatcher(runtime_registry))

        result = await runtime.run(
            RuntimeContext(request_id="req-7"),
            RuntimeTask(
                task_id="task-runtime",
                title="Generate text",
                description="Generate a test response.",
                action_type="text_generation",
                inputs={"prompt": "hello"},
            ),
            RoutingDecision(provider_id="mock", model_id="mock-model",
                            reasoning_summary="selected"),
        )

        assert result.status == TaskStatus.COMPLETED
        assert result.output == {"response": "Mock provider response"}

    asyncio.run(run_test())
