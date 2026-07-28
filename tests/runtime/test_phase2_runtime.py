import pytest

from app.core.contracts import RoutingDecision, RuntimeContext
from tests.conftest import approved_task
from app.core.contracts.planning import TaskStatus
from app.providers import MockProvider, ProviderInfo, ProviderManager, ProviderRegistry
from app.runtime import ProviderExecutor, RuntimeDispatcher, RuntimeEngine, RuntimeRegistry


@pytest.mark.asyncio
async def test_runtime_adds_timing_and_diagnostics_metadata():
    registry = ProviderRegistry()
    registry.register(
        "mock", MockProvider(),
        ProviderInfo(provider_id="mock", capabilities=[], models=[]),
    )
    provider_manager = ProviderManager(registry)
    runtime_registry = RuntimeRegistry()
    runtime_registry.register("provider", ProviderExecutor(provider_manager))
    runtime = RuntimeEngine(RuntimeDispatcher(runtime_registry))

    result = await runtime.run(
        RuntimeContext(request_id="phase2"),
        approved_task(
            task_id="task", title="Task", description="Task",
            action_type="text_generation",
        ),
        RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="test"),
    )

    assert result.status == TaskStatus.COMPLETED
    assert result.duration_ms >= 0
    assert result.metadata["runtime_request_id"] == "phase2"
