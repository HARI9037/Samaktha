import asyncio

from app.core.cap import ContextEngine
from app.core.contracts import RuntimeContext
from app.core.contracts.routing import RoutingDecision
from app.core.contracts.planning import TaskStatus
from app.core.gambit import Planner
from app.core.orchestrator import SamakthaOrchestrator
from app.providers.mock import MockProvider
from app.router import ModelRouter, ProviderModelRegistration, RouterRegistry
from app.providers.manager import ProviderManager
from app.providers.registry import ProviderRegistry
from app.providers.models import ProviderInfo
from app.runtime import (
    ProviderExecutor,
    RuntimeDispatcher,
    RuntimeEngine,
    RuntimeRegistry,
    ToolExecutor,
)
from app.tools import ToolManager, ToolRegistry


class TrackingContextEngine(ContextEngine):
    def __init__(self) -> None:
        super().__init__()
        self.called = False

    async def build(self, request):
        self.called = True
        return await super().build(request)


class TrackingPlanner(Planner):
    def __init__(self) -> None:
        super().__init__()
        self.called = False

    async def plan_with_capability_check(self, request: str):
        self.called = True
        return await super().plan_with_capability_check(request)


class TrackingRouter(ModelRouter):
    def __init__(self) -> None:
        super().__init__(
            RouterRegistry(
                [
                    ProviderModelRegistration(
                        provider_id="mock",
                        model_id="mock-model",
                        capabilities=["text_generation"],
                    )
                ]
            )
        )
        self.called = False

    async def route(self, request):
        self.called = True
        return await super().route(request)


class TrackingRuntime(RuntimeEngine):
    def __init__(self) -> None:
        provider_registry = ProviderRegistry()
        provider_registry.register("mock", MockProvider(), ProviderInfo(provider_id="mock", capabilities=["text_generation"], models=["mock-model"]))
        
        provider_executor = ProviderExecutor(ProviderManager(provider_registry))
        tool_registry = ToolRegistry()
        tool_manager = ToolManager(tool_registry)
        
        registry = RuntimeRegistry()
        registry.register("provider", provider_executor)
        registry.register("tool", ToolExecutor(tool_manager))
        
        super().__init__(RuntimeDispatcher(registry))
        self.called = False

    async def run(self, context, task, routing):
        self.called = True
        return await super().run(context, task, routing)

    async def run_batch(self, context, tasks_and_routings):
        self.called = True
        return await super().run_batch(context, tasks_and_routings)


def test_orchestrator_coordinates_cap_gambit_router_and_runtime() -> None:
    async def run_test() -> None:
        context_engine = TrackingContextEngine()
        planner = TrackingPlanner()
        router = TrackingRouter()
        runtime = TrackingRuntime()
        orchestrator = SamakthaOrchestrator(
            context_engine=context_engine,
            planner=planner,
            router=router,
            runtime=runtime,
        )

        state = await orchestrator.run_pipeline(
            request="hello",
            runtime_context=RuntimeContext(request_id="request-1", user_id="user-1"),
        )

        assert context_engine.called is True
        assert planner.called is True
        assert router.called is True
        assert runtime.called is True
        assert state.context is not None
        assert state.execution_plan is not None
        assert state.routing_decision is not None
        assert state.runtime_result is not None
        assert state.runtime_result.status == TaskStatus.COMPLETED
        assert state.runtime_result.output == {"response": "Mock provider response"}

    asyncio.run(run_test())


def test_orchestrator_returns_final_runtime_result() -> None:
    async def run_test() -> None:
        runtime = TrackingRuntime()
        orchestrator = SamakthaOrchestrator(
            context_engine=ContextEngine(),
            planner=Planner(),
            router=TrackingRouter(),
            runtime=runtime,
        )

        result = await orchestrator.run(
            request="hello",
            runtime_context=RuntimeContext(request_id="request-2"),
        )

        assert result.status == TaskStatus.COMPLETED
        assert result.output == {"response": "Mock provider response"}

    asyncio.run(run_test())
