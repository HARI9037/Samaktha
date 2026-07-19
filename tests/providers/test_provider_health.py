from app.providers import (
    MockProvider,
    OpenAIProvider,
    GroqProvider,
    LocalProvider,
    OpenRouterProvider,
    ProviderHealthChecker,
    ProviderInfo,
    ProviderManager,
    ProviderRegistry,
    ProviderSettings,
    ProviderStatus,
)


def test_provider_status_creation():
    status = ProviderStatus(
        provider_id="mock",
        enabled=True,
        configured=True,
        available=True,
        last_checked=None,
        last_error=None,
    )

    assert status.provider_id == "mock"
    assert status.reachable is False
    assert status.rate_limited is False


def test_openai_configured():
    settings = ProviderSettings(openai_api_key="test-key")
    provider = OpenAIProvider(settings)
    status = ProviderHealthChecker(settings).check("openai", provider)

    assert status.enabled is True
    assert status.configured is True
    assert status.available is True
    assert status.last_error is None


def test_openai_missing_key():
    settings = ProviderSettings(openai_api_key=None)
    provider = OpenAIProvider(settings)
    status = ProviderHealthChecker(settings).check("openai", provider)

    assert status.enabled is True
    assert status.configured is False
    assert status.available is False
    assert status.last_error == "Provider configuration is incomplete"


def test_groq_configured():
    settings = ProviderSettings(groq_api_key="test-key")
    provider = GroqProvider(settings)
    status = ProviderHealthChecker(settings).check("groq", provider)

    assert status.configured is True
    assert status.available is True


def test_openrouter_configured():
    settings = ProviderSettings(openrouter_api_key="test-key")
    provider = OpenRouterProvider(settings)
    status = ProviderHealthChecker(settings).check("openrouter", provider)

    assert status.configured is True
    assert status.available is True


def test_local_enabled():
    settings = ProviderSettings(local_base_url="http://localhost:11434")
    provider = LocalProvider(settings)
    status = ProviderHealthChecker(settings).check("local", provider)

    assert status.enabled is True
    assert status.configured is True
    assert status.available is True


def test_mock_enabled():
    settings = ProviderSettings()
    status = ProviderHealthChecker(settings).check("mock", MockProvider())

    assert status.enabled is True
    assert status.configured is True
    assert status.available is True


def test_list_provider_status():
    manager = _make_manager(ProviderSettings(openai_api_key="test-key"))

    statuses = manager.list_provider_status()

    assert {status.provider_id for status in statuses} == {"mock", "openai"}


def test_list_available_providers():
    manager = _make_manager(ProviderSettings(openai_api_key="test-key"))

    available = manager.list_available_providers()

    assert [status.provider_id for status in available] == ["mock", "openai"]


def test_list_unavailable_providers():
    manager = _make_manager(ProviderSettings(openai_api_key=None))

    unavailable = manager.list_unavailable_providers()

    assert [status.provider_id for status in unavailable] == ["openai"]


def test_disabled_provider_reported_correctly():
    settings = ProviderSettings(openai_enabled=False, openai_api_key="test-key")
    provider = OpenAIProvider(settings)
    status = ProviderHealthChecker(settings).check("openai", provider)

    assert status.enabled is False
    assert status.configured is True
    assert status.available is False
    assert status.last_error == "Provider is disabled"


def test_existing_provider_manager_behavior_still_works():
    registry = ProviderRegistry()
    provider = MockProvider()
    registry.register(
        "mock",
        provider,
        ProviderInfo(
            provider_id="mock",
            capabilities=["text_generation"],
            models=["mock-model"],
        ),
    )
    manager = ProviderManager(registry)

    assert manager.resolve_provider("mock") is provider
    assert manager.list_providers()[0].provider_id == "mock"


def _make_manager(settings: ProviderSettings) -> ProviderManager:
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
    registry.register(
        "openai",
        OpenAIProvider(settings),
        ProviderInfo(
            provider_id="openai",
            capabilities=["text_generation"],
            models=[settings.openai_model],
        ),
    )
    return ProviderManager(registry, settings)
