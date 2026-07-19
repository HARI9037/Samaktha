import asyncio

from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeTask
from app.core.contracts.planning import TaskStatus
from app.providers.mock import MockProvider
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

def build_runtime(provider_id: str = "mock") -> RuntimeEngine:
    registry = ProviderRegistry()
    registry.register(provider_id, MockProvider(), ProviderInfo(provider_id=provider_id, capabilities=["text_generation"], models=["mock-model"]))
    provider_executor = ProviderExecutor(ProviderManager(registry))
    
    tool_registry = ToolRegistry()
    tool_manager = ToolManager(tool_registry)
    
    registry = RuntimeRegistry()
    registry.register("provider", provider_executor)
    registry.register("tool", ToolExecutor(tool_manager))
    dispatcher = RuntimeDispatcher(registry)
    return RuntimeEngine(dispatcher)


def runtime_context() -> RuntimeContext:
    return RuntimeContext(request_id="request-1")


def routing_decision(provider_id: str = "mock") -> RoutingDecision:
    return RoutingDecision(
        provider_id=provider_id,
        model_id="mock-model",
        reasoning_summary="Test routing decision.",
    )


def test_runtime_engine_executes_provider_task() -> None:
    async def run_test() -> None:
        engine = build_runtime()
        task = RuntimeTask(
            task_id="task-1",
            title="Generate text",
            description="Generate a test response.",
            action_type="text_generation",
            inputs={"prompt": "hello"},
        )

        result = await engine.run(runtime_context(), task, routing_decision())

        assert result.task_id == "task-1"
        assert result.status == TaskStatus.COMPLETED
        assert result.output == {"response": "Mock provider response"}
        assert result.routing is not None
        assert result.routing.provider_id == "mock"

    asyncio.run(run_test())


def test_dispatcher_selects_provider_executor() -> None:
    registry = ProviderRegistry()
    registry.register("mock", MockProvider(), ProviderInfo(provider_id="mock", capabilities=["text_generation"], models=["mock-model"]))
    provider_executor = ProviderExecutor(ProviderManager(registry))
    registry = RuntimeRegistry()
    registry.register("provider", provider_executor)
    dispatcher = RuntimeDispatcher(registry)

    selected = dispatcher.dispatch("text_generation")

    assert selected is provider_executor


def test_provider_executor_fails_for_unknown_provider() -> None:
    async def run_test() -> None:
        registry = ProviderRegistry()
        executor = ProviderExecutor(ProviderManager(registry))
        task = RuntimeTask(
            task_id="task-2",
            title="Generate text",
            description="Generate a test response.",
            action_type="text_generation",
            inputs={"prompt": "hello"},
        )

        result = await executor.execute(runtime_context(), task, routing_decision("missing"))

        assert result.status == TaskStatus.FAILED
        assert result.error == "Provider is not registered: missing"

    asyncio.run(run_test())


def test_unknown_task_type_fails_safely() -> None:
    async def run_test() -> None:
        engine = build_runtime()
        task = RuntimeTask(
            task_id="task-3",
            title="Unknown task",
            description="Use an unknown action type.",
            action_type="unknown_action",
        )

        result = await engine.run(runtime_context(), task, routing_decision())

        assert result.status == TaskStatus.FAILED
        assert result.error == "No runtime executor registered for action type: unknown_action"

    asyncio.run(run_test())


def test_tool_execution_returns_controlled_failure() -> None:
    async def run_test() -> None:
        engine = build_runtime()
        task = RuntimeTask(
            task_id="task-4",
            title="Run tool",
            description="Attempt tool execution.",
            action_type="tool_execution",
        )

        result = await engine.run(runtime_context(), task, routing_decision())

        assert result.status == TaskStatus.FAILED
        assert "Tool not found" in result.error

    asyncio.run(run_test())
