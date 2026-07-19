import os
import pytest
from app.providers.config import ProviderSettings
from app.providers.local_provider import LocalProvider
from app.providers.manager import ProviderManager
from app.providers.mock import MockProvider
from app.providers.models import ProviderInfo
from app.providers.openai_provider import OpenAIProvider
from app.providers.registry import ProviderRegistry
from app.runtime.executor import ProviderExecutor
from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeTask
from app.core.contracts.planning import TaskStatus


def test_provider_settings_load():
    os.environ["SAMAKTHA_DEFAULT_PROVIDER"] = "openai"
    os.environ["SAMAKTHA_OPENAI_API_KEY"] = "test-key"
    settings = ProviderSettings()
    assert settings.default_provider == "openai"
    assert settings.openai_api_key == "test-key"
    assert settings.openai_model == "gpt-4o-mini"
    
    # cleanup
    del os.environ["SAMAKTHA_DEFAULT_PROVIDER"]
    del os.environ["SAMAKTHA_OPENAI_API_KEY"]


@pytest.mark.asyncio
async def test_openai_missing_key_safely():
    settings = ProviderSettings(openai_api_key=None)
    provider = OpenAIProvider(settings)
    
    result = await provider.execute({"prompt": "Hello"})
    assert result["success"] is False
    assert "missing API key" in result["message"]


@pytest.mark.asyncio
async def test_local_missing_url_safely():
    settings = ProviderSettings(local_base_url=None)
    provider = LocalProvider(settings)
    
    result = await provider.execute({"prompt": "Hello"})
    assert result["success"] is False
    assert "missing base URL" in result["message"]


def test_provider_manager_resolves_and_lists():
    registry = ProviderRegistry()
    registry.register("mock", MockProvider(), ProviderInfo(provider_id="mock", capabilities=[], models=[]))
    
    settings = ProviderSettings()
    registry.register("openai", OpenAIProvider(settings), ProviderInfo(provider_id="openai", capabilities=[], models=[]))
    
    manager = ProviderManager(registry)
    
    assert manager.resolve_provider("mock") is not None
    assert manager.resolve_provider("openai") is not None
    assert manager.resolve_provider("unknown") is None
    
    providers = manager.list_providers()
    assert len(providers) == 2


@pytest.mark.asyncio
async def test_mock_provider_still_works():
    provider = MockProvider()
    result = await provider.execute({})
    assert "Mock provider response" in result["response"]


@pytest.mark.asyncio
async def test_runtime_provider_executor_works_with_manager():
    registry = ProviderRegistry()
    registry.register("mock", MockProvider(), ProviderInfo(provider_id="mock", capabilities=[], models=[]))
    manager = ProviderManager(registry)
    executor = ProviderExecutor(manager)
    
    context = RuntimeContext(request_id="req-1")
    task = RuntimeTask(task_id="t1", title="T1", description="D", action_type="text_generation", inputs={})
    routing = RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="")
    
    result = await executor.execute(context, task, routing)
    assert result.status == TaskStatus.COMPLETED
    assert "Mock provider response" in result.output["response"]
