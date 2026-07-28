import pytest

from app.api.execute import execute_request
from app.api.schemas import ExecuteRequest
from app.core.cap import ContextEngine
from app.core.gambit import Planner
from app.core.contracts import (
    ExecutionPlan,
    Goal,
    GoalComplexity,
    RoutingDecision,
    RuntimeContext,
    RuntimeResult,
    RuntimeTask,
    RouterRequest,
)
from app.core.contracts.planning import GoalIntent, PlanTask, TaskKind, TaskStatus
from app.core.gambit import GoalParser, TaskDecomposer
from app.core.orchestrator import SamakthaOrchestrator
from app.models import ModelInfo, ModelManager, ModelRegistry
from app.providers import MockProvider, ProviderInfo, ProviderManager, ProviderRegistry
from app.router import (
    CapabilityRegistry,
    ModelRouter,
    ProviderCapability,
    ProviderModelRegistration,
    RouterRegistry,
)
from app.runtime import ProviderExecutor
from app.workflow.engine import WorkflowEngine


class RecordingRuntime:
    def __init__(self):
        self.called = False

    async def run(self, context, task, routing):
        self.called = True
        return RuntimeResult(
            task_id=task.task_id,
            status=TaskStatus.COMPLETED,
            routing=routing,
            output={"content": "ok"},
        )


def _router():
    return ModelRouter(RouterRegistry([
        ProviderModelRegistration(
            provider_id="mock",
            model_id="mock-model",
            capabilities=["text_generation"],
        ),
    ]))


@pytest.mark.asyncio
async def test_cap_governance_blocks_sensitive_runtime_execution():
    runtime = RecordingRuntime()
    orchestrator = SamakthaOrchestrator(
        context_engine=ContextEngine(),
        planner=Planner(),
        router=_router(),
        runtime=runtime,
    )

    result = await orchestrator.run(
        request="process my bank details",
        runtime_context=RuntimeContext(request_id="cap-test"),
    )

    assert result.status == TaskStatus.FAILED
    assert result.metadata["governance_decision"] == "ask_user"
    assert runtime.called is False


@pytest.mark.asyncio
async def test_provider_executor_requires_provider_manager_execution_interface():
    class Manager:
        def resolve_provider(self, provider_id):
            raise AssertionError("direct provider resolution must not be used")

        async def execute_provider(self, provider_id, payload, model_id=None, required_capabilities=None):
            return {
                "success": True,
                "content": "manager result",
                "provider_id": provider_id,
                "model_id": model_id,
            }

    result = await ProviderExecutor(Manager()).execute(
        RuntimeContext(request_id="runtime-test"),
        RuntimeTask(
            task_id="task",
            title="Task",
            description="Task",
            action_type="text_generation",
        ),
        RoutingDecision(
            provider_id="mock",
            model_id="mock-model",
            reasoning_summary="test",
        ),
    )

    assert result.status == TaskStatus.COMPLETED
    assert result.output["content"] == "manager result"


def test_workflow_preserves_planned_execution_action_type():
    task = PlanTask(
        task_id="tool-task",
        title="Use tool",
        kind=TaskKind.EXECUTE_VIA_RUNTIME,
        description="Use the tool",
        execution_action_type="tool_execution",
    )
    plan = ExecutionPlan(
        plan_id="plan",
        goal=Goal(
            goal_id="goal",
            raw_request="tool",
            summary="tool",
            complexity=GoalComplexity.LOW,
        ),
        tasks=[task],
        workflow=[],
        router_request=RouterRequest(
            purpose="tool_execution",
            complexity=GoalComplexity.LOW,
            estimated_context_tokens=10,
            requires_local_model=False,
            requires_code=False,
            requires_reasoning=False,
        ),
    )

    workflow_task = WorkflowEngine._workflow_tasks(plan)[0]

    assert workflow_task.runtime_task.action_type == "tool_execution"


@pytest.mark.parametrize("user_request", ["list desktop", "browse desktop", "dir desktop", "ls desktop"])
def test_directory_listing_action_reaches_runtime_task_arguments(user_request):
    goal = GoalParser().parse(user_request)
    assert goal.intent == GoalIntent.LIST_DIRECTORY

    task = next(
        task
        for task in TaskDecomposer().decompose(goal, skill_matches=[])
        if task.execution_action_type == "tool"
    )
    assert task.metadata["tool"] == "resolver"
    assert task.metadata["action"] == "list"

    plan = ExecutionPlan(
        plan_id="plan",
        goal=goal,
        tasks=[task],
        workflow=[],
        router_request=RouterRequest(
            purpose="directory_listing",
            complexity=GoalComplexity.LOW,
            estimated_context_tokens=10,
            requires_local_model=False,
            requires_code=False,
            requires_reasoning=False,
        ),
    )

    runtime_task = WorkflowEngine._workflow_tasks(plan)[0].runtime_task

    assert runtime_task.action_type == "tool"
    assert runtime_task.metadata["tool"] == "resolver"
    assert runtime_task.metadata["action"] == "list"
    assert runtime_task.inputs["action"] == "list"
    assert runtime_task.inputs["path"] == goal.target_path


@pytest.mark.asyncio
async def test_api_prefers_normalized_provider_content():
    class Orchestrator:
        async def run(self, request, runtime_context):
            return RuntimeResult(
                task_id="task",
                status=TaskStatus.COMPLETED,
                output={"content": "normalized content"},
            )

    response = await execute_request(
        ExecuteRequest(message="hello"),
        orchestrator=Orchestrator(),
    )

    assert response.response == "normalized content"


def test_capability_registry_supports_multiple_models_per_provider():
    registry = CapabilityRegistry()
    first = ProviderCapability(
        provider_id="provider",
        model_id="model-a",
        capabilities=["text_generation"],
    )
    second = ProviderCapability(
        provider_id="provider",
        model_id="model-b",
        capabilities=["text_generation"],
    )

    registry.register(first)
    registry.register(second)

    assert registry.get("provider", "model-a") is first
    assert registry.get("provider", "model-b") is second
    assert len(registry.all()) == 2


@pytest.mark.asyncio
async def test_router_uses_model_registry_as_canonical_metadata_source():
    models = ModelRegistry()
    models.register(ModelInfo(
        model_id="model-a",
        provider_id="provider",
        display_name="Model A",
        context_window=4096,
        supports_tools=False,
        supports_streaming=False,
        supports_images=False,
        supports_audio=False,
        reasoning_score=10,
        coding_score=10,
        speed_score=10,
        cost_score=10,
        privacy_score=10,
    ))
    capabilities = CapabilityRegistry()
    capabilities.register(ProviderCapability(
        provider_id="provider",
        model_id="model-a",
        capabilities=["text_generation"],
        reasoning_score=1,
        coding_score=1,
        speed_score=1,
        cost_score=1,
        privacy_score=1,
    ))
    router = ModelRouter(
        RouterRegistry([
            ProviderModelRegistration(
                provider_id="provider",
                model_id="model-a",
                capabilities=["text_generation"],
            ),
        ]),
        capability_registry=capabilities,
        model_manager=ModelManager(models),
    )

    decision = await router.route(RouterRequest(
        purpose="text_generation",
        complexity=GoalComplexity.HIGH,
        estimated_context_tokens=10,
        requires_local_model=False,
        requires_code=True,
        requires_reasoning=True,
    ))

    assert decision.provider_id == "provider"
    assert decision.metadata["score"] != "6"


@pytest.mark.asyncio
async def test_provider_executor_uses_real_manager_with_mock_provider():
    registry = ProviderRegistry()
    registry.register(
        "mock",
        MockProvider(),
        ProviderInfo(
            provider_id="mock",
            capabilities=["text_generation"],
            models=["mock-model"],
        ),
    )
    result = await ProviderExecutor(ProviderManager(registry)).execute(
        RuntimeContext(request_id="provider-test"),
        RuntimeTask(
            task_id="task",
            title="Task",
            description="Task",
            action_type="text_generation",
        ),
        RoutingDecision(
            provider_id="mock",
            model_id="mock-model",
            reasoning_summary="test",
        ),
    )

    assert result.status == TaskStatus.COMPLETED
