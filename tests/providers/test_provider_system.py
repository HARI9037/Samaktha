import pytest

from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeTask
from app.core.contracts.planning import TaskStatus
from app.providers import MockProvider, ProviderInfo, ProviderManager, ProviderRegistry
from app.runtime.executor import ProviderExecutor


def test_provider_registry_registers_provider():
    registry = ProviderRegistry()
    info = ProviderInfo(provider_id="mock", capabilities=["text_generation"], models=["mock-model"])
    provider = MockProvider()
    registry.register("mock", provider, info)
    
    assert len(registry.list_providers()) == 1
    assert registry.list_providers()[0].provider_id == "mock"


def test_provider_registry_retrieves_provider():
    registry = ProviderRegistry()
    info = ProviderInfo(provider_id="mock", capabilities=["text_generation"], models=["mock-model"])
    provider = MockProvider()
    registry.register("mock", provider, info)
    
    retrieved = registry.get_provider("mock")
    assert retrieved is provider


def test_provider_manager_resolves_provider():
    registry = ProviderRegistry()
    info = ProviderInfo(provider_id="mock", capabilities=["text_generation"], models=["mock-model"])
    provider = MockProvider()
    registry.register("mock", provider, info)
    manager = ProviderManager(registry)
    
    retrieved = manager.resolve_provider("mock")
    assert retrieved is provider


@pytest.mark.asyncio
async def test_mock_provider_executes_successfully():
    provider = MockProvider()
    result = await provider.execute({"prompt": "Hello"})
    assert result == {"response": "Mock provider response"}


@pytest.mark.asyncio
async def test_runtime_provider_executor_works_through_manager():
    registry = ProviderRegistry()
    info = ProviderInfo(provider_id="mock", capabilities=["text_generation"], models=["mock-model"])
    registry.register("mock", MockProvider(), info)
    manager = ProviderManager(registry)
    
    executor = ProviderExecutor(manager)
    context = RuntimeContext(request_id="req-1")
    task = RuntimeTask(task_id="task-1", title="Test", description="Test task", action_type="text_generation", inputs={"prompt": "Hello"})
    routing = RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="test")
    
    result = await executor.execute(context, task, routing)
    
    assert result.status == TaskStatus.COMPLETED
    assert result.output == {"response": "Mock provider response"}


@pytest.mark.asyncio
async def test_unknown_provider_fails_safely():
    registry = ProviderRegistry()
    manager = ProviderManager(registry)
    
    executor = ProviderExecutor(manager)
    context = RuntimeContext(request_id="req-2")
    task = RuntimeTask(task_id="task-2", title="Test", description="Test task", action_type="text_generation", inputs={})
    routing = RoutingDecision(provider_id="unknown", model_id="unknown-model", reasoning_summary="test")
    
    result = await executor.execute(context, task, routing)
    
    assert result.status == TaskStatus.FAILED
    assert "Provider is not registered" in result.error
