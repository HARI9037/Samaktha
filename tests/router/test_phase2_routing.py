import pytest

from app.core.contracts.planning import GoalComplexity, RouterRequest
from app.models import ModelInfo, ModelManager, ModelRegistry
from app.router import (
    CapabilityRegistry,
    ModelRouter,
    ProviderCapability,
    ProviderModelRegistration,
    RouterRegistry,
    RoutingPolicy,
    ScoringEngine,
)


def _request(**overrides):
    values = {
        "purpose": "text_generation",
        "complexity": GoalComplexity.LOW,
        "estimated_context_tokens": 100,
        "requires_local_model": False,
        "requires_code": False,
        "requires_reasoning": False,
        "requires_fast_response": False,
    }
    values.update(overrides)
    return RouterRequest(**values)


def test_scoring_filters_context_and_latency_constraints():
    registry = CapabilityRegistry()
    registry.register(ProviderCapability(
        provider_id="small", model_id="small-v1", capabilities=["text_generation"],
        context_window=64, latency_ms=10,
    ))
    registry.register(ProviderCapability(
        provider_id="large", model_id="large-v2", capabilities=["text_generation"],
        context_window=4096, latency_ms=20,
    ))

    ranked = ScoringEngine().rank(
        _request(estimated_context_tokens=100, max_latency_ms=25),
        registry.all(),
    )

    assert [item.provider_id for item in ranked] == ["large"]


@pytest.mark.asyncio
async def test_router_uses_model_registry_context_metadata():
    models = ModelRegistry()
    models.register(ModelInfo(
        model_id="small-v1", provider_id="small", display_name="Small",
        context_window=32, supports_tools=False, supports_streaming=False,
        supports_images=False, supports_audio=False, reasoning_score=5,
        coding_score=5, speed_score=5, cost_score=5, privacy_score=5,
    ))
    router = ModelRouter(
        RouterRegistry([
            ProviderModelRegistration(
                provider_id="small", model_id="small-v1",
                capabilities=["text_generation"],
            ),
        ]),
        model_manager=ModelManager(models),
    )

    decision = await router.route(_request(estimated_context_tokens=100))

    assert decision.provider_id == ""
    assert "model_constraints" in decision.constraints[0]


def test_model_registry_batch_and_metadata_update():
    registry = ModelRegistry()
    manager = ModelManager(registry)
    model = ModelInfo(
        model_id="model-v1", provider_id="mock", display_name="Model",
        context_window=1024, supports_tools=False, supports_streaming=False,
        supports_images=False, supports_audio=False, reasoning_score=5,
        coding_score=5, speed_score=5, cost_score=5, privacy_score=5,
        version="1.0",
    )

    manager.register_models([model])
    manager.update_model_metadata(model)

    assert manager.resolve_model("model-v1").capability_source == "metadata"
