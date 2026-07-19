from app.providers import (
    MockProvider,
    OpenAIProvider,
    ProviderInfo,
    ProviderManager,
    ProviderRegistry,
    ProviderSettings,
)


def test_preferred_provider_selected():
    settings = ProviderSettings(openai_api_key="test-key")
    manager = _make_manager(settings)

    selected = manager.select_provider(
        required_capabilities=["text_generation"],
        preferred_provider="openai",
    )

    assert selected.provider_id == "openai"


def test_disabled_provider_ignored():
    settings = ProviderSettings(openai_enabled=False, openai_api_key="test-key")
    manager = _make_manager(settings)

    selected = manager.select_provider(
        required_capabilities=["text_generation"],
        preferred_provider="openai",
    )

    assert selected.provider_id == "mock"


def test_missing_api_key_ignored():
    settings = ProviderSettings(openai_api_key=None)
    manager = _make_manager(settings)

    selected = manager.select_provider(required_capabilities=["code_generation"])

    assert selected is None


def test_capability_filtering():
    settings = ProviderSettings(openai_api_key="test-key")
    manager = _make_manager(settings)

    selected = manager.select_provider(required_capabilities=["code_generation"])

    assert selected.provider_id == "openai"


def test_preferred_model_honored():
    settings = ProviderSettings(openai_api_key="test-key")
    manager = _make_manager(settings)

    selected = manager.select_provider(
        required_capabilities=["text_generation"],
        preferred_model="gpt-4o-mini",
    )

    assert selected.provider_id == "openai"


def test_deterministic_ordering():
    settings = ProviderSettings(openai_api_key="test-key")
    manager = _make_manager(settings)

    selected = manager.select_provider(required_capabilities=["text_generation"])

    assert selected.provider_id == "mock"


def test_unknown_provider_returns_none():
    settings = ProviderSettings(openai_api_key="test-key")
    manager = _make_manager(settings)

    selected = manager.select_provider(
        required_capabilities=["text_generation"],
        preferred_provider="unknown",
    )

    assert selected is None


def test_provider_manager_delegates_correctly():
    selection_engine = RecordingSelectionEngine()
    manager = ProviderManager(
        registry=ProviderRegistry(),
        selection_engine=selection_engine,
    )

    selected = manager.select_provider(
        required_capabilities=["text_generation"],
        preferred_provider="mock",
        preferred_model="mock-model",
    )

    assert selected.provider_id == "mock"
    assert selection_engine.calls == [
        (["text_generation"], "mock", "mock-model"),
    ]


class RecordingSelectionEngine:
    def __init__(self) -> None:
        self.calls = []

    def select_provider(
        self,
        required_capabilities,
        preferred_provider=None,
        preferred_model=None,
    ):
        self.calls.append(
            (required_capabilities, preferred_provider, preferred_model),
        )
        return ProviderInfo(
            provider_id="mock",
            capabilities=["text_generation"],
            models=["mock-model"],
            supported_models=["mock-model"],
        )


def _make_manager(settings: ProviderSettings) -> ProviderManager:
    registry = ProviderRegistry()
    registry.register(
        "mock",
        MockProvider(),
        ProviderInfo(
            provider_id="mock",
            capabilities=["text_generation"],
            models=["mock-model"],
            supported_models=["mock-model"],
        ),
    )
    registry.register(
        "openai",
        OpenAIProvider(settings),
        ProviderInfo(
            provider_id="openai",
            capabilities=["text_generation", "code_generation"],
            models=[settings.openai_model],
            supported_models=["gpt-4o", "gpt-4o-mini"],
        ),
    )
    return ProviderManager(registry, settings)
