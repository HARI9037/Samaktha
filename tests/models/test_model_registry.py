from app.models import ModelInfo, ModelRegistry


def make_model(
    model_id: str = "test-model",
    provider_id: str = "test-provider",
    display_name: str = "Test Model",
) -> ModelInfo:
    return ModelInfo(
        model_id=model_id,
        provider_id=provider_id,
        display_name=display_name,
        context_window=4096,
        supports_tools=False,
        supports_streaming=False,
        supports_images=False,
        supports_audio=False,
        reasoning_score=5,
        coding_score=5,
        speed_score=5,
        cost_score=5,
        privacy_score=5,
    )


def test_model_registry_registers_model():
    registry = ModelRegistry()
    model = make_model()

    registry.register(model)

    assert registry.list_models() == [model]


def test_model_registry_looks_up_model():
    registry = ModelRegistry()
    model = make_model()
    registry.register(model)

    assert registry.get("test-model") is model


def test_model_registry_filters_by_provider():
    registry = ModelRegistry()
    openai_model = make_model("gpt-4o-mini", "openai", "GPT-4o mini")
    local_model = make_model("local-default", "local", "Local Default")
    registry.register(openai_model)
    registry.register(local_model)

    assert registry.list_by_provider("openai") == [openai_model]


def test_model_registry_duplicate_registration_overwrites_model():
    registry = ModelRegistry()
    original = make_model(display_name="Original")
    replacement = make_model(display_name="Replacement")

    registry.register(original)
    registry.register(replacement)

    assert registry.list_models() == [replacement]
    assert registry.get("test-model").display_name == "Replacement"


def test_model_registry_unknown_model_returns_none():
    registry = ModelRegistry()

    assert registry.get("unknown-model") is None
