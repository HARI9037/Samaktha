import pytest

from app.core.contracts.planning import RouterRequest
from app.router.router import ModelRouter
from app.router.registry import RouterRegistry
from app.providers.health import ProviderHealthChecker


@pytest.fixture
def mock_health_checker():
    return ProviderHealthChecker()


@pytest.fixture
def router_registry():
    from app.router.models import ProviderModelRegistration
    registry = RouterRegistry()
    registry.register(ProviderModelRegistration(
        provider_id="healthy_provider",
        model_id="model-1",
        capabilities=["text_generation"],
    ))
    registry.register(ProviderModelRegistration(
        provider_id="unhealthy_provider",
        model_id="model-2",
        capabilities=["text_generation"],
    ))
    return registry


@pytest.mark.asyncio
async def test_router_avoids_unhealthy_providers(router_registry, mock_health_checker):
    # Mark unhealthy_provider as failing
    mock_health_checker.record_failure("unhealthy_provider", "Timeout")

    # Mark healthy_provider with successful history
    mock_health_checker.record_success("healthy_provider", 100.0)

    router = ModelRouter(
        registry=router_registry,
        health_checker=mock_health_checker,
    )

    request = RouterRequest(
        task_id="task-1",
        purpose="Generate text",
        estimated_context_tokens=100,
        complexity="low",
        requires_local_model=False,
        requires_code=False,
        requires_reasoning=False,
    )

    decision = await router.route(request)

    assert decision.provider_id == "healthy_provider"
