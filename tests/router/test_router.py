import asyncio

from app.core.contracts import RouterRequest
from app.core.contracts.planning import GoalComplexity, TaskStatus
from app.core.contracts.runtime import RuntimeContext
from app.core.orchestrator import SamakthaOrchestrator
from app.core.cap import ContextEngine
from app.core.gambit import Planner
from app.providers.mock import MockProvider
from app.providers.manager import ProviderManager
from app.providers.registry import ProviderRegistry
from app.providers.models import ProviderInfo
from app.router import ModelRouter, ProviderModelRegistration, RouterRegistry
from app.runtime import ProviderExecutor, RuntimeDispatcher, RuntimeEngine, RuntimeRegistry, ToolExecutor
from app.tools import ToolManager, ToolRegistry


def router_request(
    purpose: str = "text_generation: hello",
    requires_code: bool = False,
) -> RouterRequest:
    return RouterRequest(
        purpose=purpose,
        complexity=GoalComplexity.LOW,
        estimated_context_tokens=2000,
        requires_local_model=False,
        requires_code=requires_code,
        requires_reasoning=False,
    )


def test_provider_registration_works() -> None:
    registry = RouterRegistry()
    registration = ProviderModelRegistration(
        provider_id="mock",
        model_id="mock-model",
        capabilities=["text_generation"],
    )

    registry.register(registration)

    assert registry.all() == [registration]
    assert registry.candidates("text_generation") == [registration]


def test_router_finds_matching_capability() -> None:
    async def run_test() -> None:
        registry = RouterRegistry(
            [
                ProviderModelRegistration(
                    provider_id="mock",
                    model_id="mock-model",
                    capabilities=["text_generation"],
                )
            ]
        )
        router = ModelRouter(registry)

        decision = await router.route(router_request())

        assert decision.provider_id == "mock"
        assert decision.model_id == "mock-model"
        assert decision.metadata["capability"] == "text_generation"

    asyncio.run(run_test())


def test_router_returns_correct_routing_decision() -> None:
    async def run_test() -> None:
        router = ModelRouter(
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

        decision = await router.route(router_request())

        assert decision.reasoning_summary == (
            "Selected mock/mock-model for capability: text_generation"
        )
        assert decision.constraints == []

    asyncio.run(run_test())


def test_router_handles_unknown_capability_safely() -> None:
    async def run_test() -> None:
        router = ModelRouter(RouterRegistry())

        decision = await router.route(router_request(requires_code=True))

        assert decision.provider_id == ""
        assert decision.model_id == ""
        assert decision.constraints == ["missing_capability:code_generation"]

    asyncio.run(run_test())


def test_existing_orchestrator_execution_still_works() -> None:
    async def run_test() -> None:
        provider_registry = ProviderRegistry()
        provider_registry.register("mock", MockProvider(), ProviderInfo(provider_id="mock", capabilities=["text_generation"], models=["mock-model"]))
        provider_executor = ProviderExecutor(ProviderManager(provider_registry))

        tool_registry = ToolRegistry()
        tool_manager = ToolManager(tool_registry)

        runtime_registry = RuntimeRegistry()
        runtime_registry.register("provider", provider_executor)
        runtime_registry.register("tool", ToolExecutor(tool_manager))
        router_registry = RouterRegistry(
            [
                ProviderModelRegistration(
                    provider_id="mock",
                    model_id="mock-model",
                    capabilities=["text_generation"],
                )
            ]
        )
        orchestrator = SamakthaOrchestrator(
            context_engine=ContextEngine(),
            planner=Planner(),
            router=ModelRouter(router_registry),
            runtime=RuntimeEngine(RuntimeDispatcher(runtime_registry)),
        )

        result = await orchestrator.run(
            request="hello",
            runtime_context=RuntimeContext(request_id="request-1"),
        )

        assert result.status == TaskStatus.COMPLETED
        assert result.output == {"response": "Mock provider response"}

    asyncio.run(run_test())
