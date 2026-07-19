from app.models import ModelInfo, ModelManager, ModelRegistry


def make_model(
    model_id: str = "test-model",
    provider_id: str = "test-provider",
) -> ModelInfo:
    return ModelInfo(
        model_id=model_id,
        provider_id=provider_id,
        display_name="Test Model",
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


class RecordingModelRegistry(ModelRegistry):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, str | None]] = []

    def register(self, model: ModelInfo) -> None:
        self.calls.append(("register", model.model_id))
        super().register(model)

    def get(self, model_id: str):
        self.calls.append(("get", model_id))
        return super().get(model_id)

    def list_models(self):
        self.calls.append(("list_models", None))
        return super().list_models()

    def list_by_provider(self, provider_id: str):
        self.calls.append(("list_by_provider", provider_id))
        return super().list_by_provider(provider_id)


def test_model_manager_registers_model_through_registry():
    registry = RecordingModelRegistry()
    manager = ModelManager(registry)
    model = make_model()

    manager.register_model(model)

    assert registry.calls == [("register", "test-model")]
    assert registry.get("test-model") is model


def test_model_manager_resolves_model_through_registry():
    registry = RecordingModelRegistry()
    model = make_model()
    registry.register(model)
    registry.calls.clear()
    manager = ModelManager(registry)

    assert manager.resolve_model("test-model") is model
    assert registry.calls == [("get", "test-model")]


def test_model_manager_lists_models_through_registry():
    registry = RecordingModelRegistry()
    model = make_model()
    registry.register(model)
    registry.calls.clear()
    manager = ModelManager(registry)

    assert manager.list_models() == [model]
    assert registry.calls == [("list_models", None)]


def test_model_manager_lists_models_by_provider_through_registry():
    registry = RecordingModelRegistry()
    model = make_model(provider_id="openai")
    registry.register(model)
    registry.calls.clear()
    manager = ModelManager(registry)

    assert manager.list_models_by_provider("openai") == [model]
    assert registry.calls == [("list_by_provider", "openai")]


def test_model_manager_unknown_model_returns_none():
    manager = ModelManager(ModelRegistry())

    assert manager.resolve_model("unknown-model") is None
