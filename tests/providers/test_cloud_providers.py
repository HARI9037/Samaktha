import os

import pytest

from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeTask
from app.core.contracts.planning import TaskStatus
from app.providers import (
    GroqProvider,
    LocalProvider,
    MockProvider,
    OpenAIProvider,
    OpenRouterProvider,
    ProviderInfo,
    ProviderManager,
    ProviderRegistry,
    ProviderSettings,
)
from app.runtime.executor import ProviderExecutor


def _register_all_providers(registry: ProviderRegistry, settings: ProviderSettings) -> None:
    registry.register(
        "mock",
        MockProvider(),
        ProviderInfo(provider_id="mock", capabilities=["text_generation"], models=["mock-model"]),
    )
    registry.register(
        "openai",
        OpenAIProvider(settings),
        ProviderInfo(provider_id="openai", capabilities=["text_generation"], models=[settings.openai_model]),
    )
    registry.register(
        "groq",
        GroqProvider(settings),
        ProviderInfo(provider_id="groq", capabilities=["text_generation"], models=[settings.groq_model]),
    )
    registry.register(
        "openrouter",
        OpenRouterProvider(settings),
        ProviderInfo(
            provider_id="openrouter",
            capabilities=["text_generation"],
            models=[settings.openrouter_model],
        ),
    )
    registry.register(
        "local",
        LocalProvider(settings),
        ProviderInfo(
            provider_id="local",
            capabilities=["text_generation"],
            models=[settings.local_model or "unknown"],
        ),
    )


@pytest.mark.asyncio
async def test_groq_missing_key_safely():
    settings = ProviderSettings(groq_api_key=None)
    provider = GroqProvider(settings)

    result = await provider.execute({"prompt": "Hello"})
    assert result["success"] is False
    assert result["message"] == "Groq provider unavailable: missing API key"


@pytest.mark.asyncio
async def test_openrouter_missing_key_safely():
    settings = ProviderSettings(openrouter_api_key=None)
    provider = OpenRouterProvider(settings)

    result = await provider.execute({"prompt": "Hello"})
    assert result["success"] is False
    assert result["message"] == "OpenRouter provider unavailable: missing API key"


def test_provider_settings_loads_groq_config():
    os.environ["SAMAKTHA_GROQ_API_KEY"] = "test-groq-key"
    os.environ["SAMAKTHA_GROQ_MODEL"] = "openai/gpt-oss-120b"
    os.environ["SAMAKTHA_GROQ_BASE_URL"] = "https://api.groq.com/openai/v1"

    settings = ProviderSettings()
    assert settings.groq_api_key == "test-groq-key"
    assert settings.groq_model == "openai/gpt-oss-120b"
    assert settings.groq_base_url == "https://api.groq.com/openai/v1"

    del os.environ["SAMAKTHA_GROQ_API_KEY"]
    del os.environ["SAMAKTHA_GROQ_MODEL"]
    del os.environ["SAMAKTHA_GROQ_BASE_URL"]


def test_provider_settings_loads_openrouter_config():
    os.environ["SAMAKTHA_OPENROUTER_API_KEY"] = "test-openrouter-key"
    os.environ["SAMAKTHA_OPENROUTER_MODEL"] = "openai/gpt-oss-120b"
    os.environ["SAMAKTHA_OPENROUTER_BASE_URL"] = "https://openrouter.ai/api/v1"

    settings = ProviderSettings()
    assert settings.openrouter_api_key == "test-openrouter-key"
    assert settings.openrouter_model == "openai/gpt-oss-120b"
    assert settings.openrouter_base_url == "https://openrouter.ai/api/v1"

    del os.environ["SAMAKTHA_OPENROUTER_API_KEY"]
    del os.environ["SAMAKTHA_OPENROUTER_MODEL"]
    del os.environ["SAMAKTHA_OPENROUTER_BASE_URL"]


def test_provider_registry_registers_five_providers():
    registry = ProviderRegistry()
    _register_all_providers(registry, ProviderSettings())

    provider_ids = {info.provider_id for info in registry.list_providers()}
    assert provider_ids == {"mock", "openai", "groq", "openrouter", "local"}


def test_provider_manager_resolves_all_providers():
    registry = ProviderRegistry()
    _register_all_providers(registry, ProviderSettings())
    manager = ProviderManager(registry)

    for provider_id in ("mock", "openai", "groq", "openrouter", "local"):
        assert manager.resolve_provider(provider_id) is not None


@pytest.mark.asyncio
async def test_mock_provider_still_works():
    provider = MockProvider()
    result = await provider.execute({"prompt": "Hello"})
    assert result == {"response": "Mock provider response"}


@pytest.mark.asyncio
async def test_runtime_provider_executor_still_works():
    registry = ProviderRegistry()
    _register_all_providers(registry, ProviderSettings())
    manager = ProviderManager(registry)
    executor = ProviderExecutor(manager)

    context = RuntimeContext(request_id="req-cloud-1")
    task = RuntimeTask(
        task_id="task-cloud-1",
        title="Test",
        description="Test task",
        action_type="text_generation",
        inputs={"prompt": "Hello"},
    )
    routing = RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="test")

    result = await executor.execute(context, task, routing)

    assert result.status == TaskStatus.COMPLETED
    assert result.output == {"response": "Mock provider response"}
