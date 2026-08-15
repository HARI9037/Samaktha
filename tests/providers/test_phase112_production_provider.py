import asyncio

import pytest

from app.core.contracts import RouterRequest
from app.core.contracts.planning import GoalComplexity
from app.core.contracts.streaming import StreamEventType, StreamRequest
from app.core.orchestrator import SamakthaOrchestrator
from app.providers import (
    BaseProvider,
    ProviderHealthChecker,
    ProviderInfo,
    ProviderManager,
    ProviderRegistry,
    ProviderSettings,
    ProviderStartupError,
)
from app.router import ModelRouter, ProviderModelRegistration, RouterRegistry


def router_request(
    purpose: str = "text_generation: hello",
    requires_code: bool = False,
) -> RouterRequest:
    return RouterRequest(
        purpose=purpose,
        complexity=GoalComplexity.LOW,
        estimated_context_tokens=2000,
        requires_local_model=False,
        requires_code=requires_code,
        requires_reasoning=False,
    )


class FailingProvider(BaseProvider):
    @property
    def name(self) -> str:
        return "failing"

    async def execute(self, payload: dict) -> dict:
        return {
            "success": False,
            "finish_reason": "http_error",
            "message": "invalid API key",
            "content": "",
            "provider_id": "failing",
        }

    async def execute_stream(self, payload: dict):
        raise RuntimeError("stream boom")
        yield  # pragma: no cover

    def supports(self, capability) -> bool:
        return True

    async def health_check(self) -> bool:
        return True


class WorkingProvider(BaseProvider):
    @property
    def name(self) -> str:
        return "working"

    async def execute(self, payload: dict) -> dict:
        return {"success": True, "content": "ok", "provider_id": "working"}

    async def execute_stream(self, payload: dict):
        yield "tok1"
        yield "tok2"

    def supports(self, capability) -> bool:
        return True

    async def health_check(self) -> bool:
        return True


def _register(registry: ProviderRegistry, provider_id: str, provider: BaseProvider) -> None:
    registry.register(
        provider_id,
        provider,
        ProviderInfo(
            provider_id=provider_id,
            capabilities=["text_generation"],
            models=["m"],
            supported_models=["m"],
        ),
    )


def _manager() -> ProviderManager:
    registry = ProviderRegistry()
    _register(registry, "failing", FailingProvider())
    _register(registry, "working", WorkingProvider())
    settings = ProviderSettings(
        _env_file=None,
        fallback_enabled=True,
        cooldown_seconds=60,
        max_retries=0,
    )
    return ProviderManager(registry, settings)


# --- O1/O2: startup validation fails loudly, no silent downgrade -----------


def test_missing_default_api_key_fails_startup():
    settings = ProviderSettings(_env_file=None, default_provider="groq", groq_api_key=None)
    with pytest.raises(ProviderStartupError, match="Groq API key missing"):
        settings.validate_startup()


def test_disabled_default_provider_fails_startup():
    settings = ProviderSettings(
        _env_file=None,
        default_provider="openai",
        openai_enabled=False,
        openai_api_key="test-key",
    )
    with pytest.raises(ProviderStartupError, match="Openai is disabled"):
        settings.validate_startup()


def test_no_silent_provider_downgrade():
    settings = ProviderSettings(_env_file=None, default_provider="groq", groq_api_key=None)
    assert settings.default_provider == "groq"
    with pytest.raises(ProviderStartupError):
        settings.validate_startup()


def test_no_production_provider_configured_fails_production_validation():
    settings = ProviderSettings(
        _env_file=None,
        default_provider="groq",
        groq_api_key=None,
        openai_api_key=None,
        openrouter_api_key=None,
        local_base_url=None,
    )
    with pytest.raises(ProviderStartupError, match="No production provider is configured"):
        settings.validate_production()


def test_configured_provider_passes_startup_validation():
    settings = ProviderSettings(_env_file=None, default_provider="groq", groq_api_key="test-key")
    settings.validate_startup()
    settings.validate_production()


# --- O3: mock is development only ------------------------------------------


def test_mock_rejected_in_production():
    settings = ProviderSettings(_env_file=None, default_provider="mock")
    with pytest.raises(ProviderStartupError, match="Mock provider is not available in production"):
        settings.validate_startup()


def test_mock_allowed_in_dev_mode():
    settings = ProviderSettings(_env_file=None, default_provider="mock", dev_mode=True)
    settings.validate_startup()
    settings.validate_production()


def test_mock_allowed_with_mock_agent_flag():
    settings = ProviderSettings(_env_file=None, default_provider="mock", mock_agent=True)
    settings.validate_startup()


# --- O4: deterministic fallback + cooldown on failure ----------------------


def test_invalid_api_key_falls_back_and_marks_cooldown():
    async def run_test() -> None:
        manager = _manager()
        result = await manager.execute_provider("failing", {"prompt": "hi"}, model_id="m")
        assert result["success"] is True
        assert result["content"] == "ok"
        assert manager._is_in_cooldown("failing") is True
        assert manager.get_provider_status("failing").rate_limited is True

    asyncio.run(run_test())


def test_streaming_falls_back_to_next_healthy_provider():
    async def run_test() -> None:
        manager = _manager()
        request = StreamRequest(
            request_id="r1",
            provider_id="failing",
            prompt="hi",
            capabilities=["text_generation"],
        )
        chunks = [chunk async for chunk in manager.stream_provider(request)]
        events = [chunk.event_type for chunk in chunks]
        assert StreamEventType.STARTED in events
        assert StreamEventType.COMPLETED in events
        tokens = "".join(
            chunk.content for chunk in chunks if chunk.event_type == StreamEventType.TOKEN
        )
        assert tokens == "tok1tok2"
        completed = next(
            chunk for chunk in chunks if chunk.event_type == StreamEventType.COMPLETED
        )
        assert completed.metadata["provider_id"] == "working"
        assert manager._is_in_cooldown("failing") is True

    asyncio.run(run_test())


def test_streaming_raises_loud_error_when_all_candidates_fail():
    async def run_test() -> None:
        registry = ProviderRegistry()
        _register(registry, "failing", FailingProvider())
        _register(registry, "failing2", FailingProvider())
        manager = ProviderManager(
            registry,
            ProviderSettings(_env_file=None, fallback_enabled=True, cooldown_seconds=60),
        )
        request = StreamRequest(
            request_id="r2",
            provider_id="failing",
            prompt="hi",
            capabilities=["text_generation"],
        )
        with pytest.raises(RuntimeError, match="Provider 'failing2' stream failed: stream boom"):
            async for _ in manager.stream_provider(request):
                pass

    asyncio.run(run_test())


def test_streaming_raises_unavailable_when_no_candidate_is_healthy():
    async def run_test() -> None:
        manager = _manager()
        manager._health_checker.mark_cooldown("failing", seconds=60)
        manager._health_checker.mark_cooldown("working", seconds=60)
        request = StreamRequest(
            request_id="r3",
            provider_id="failing",
            prompt="hi",
            capabilities=["text_generation"],
        )
        with pytest.raises(RuntimeError, match="Provider 'failing' is currently unavailable"):
            async for _ in manager.stream_provider(request):
                pass

    asyncio.run(run_test())


# --- O7: router consults health + cooldown during selection ----------------


def test_router_skips_provider_in_cooldown():
    async def run_test() -> None:
        settings = ProviderSettings(_env_file=None, openai_api_key="test-key")
        health = ProviderHealthChecker(settings)
        registry = RouterRegistry(
            [
                ProviderModelRegistration(
                    provider_id="mock", model_id="mock-model", capabilities=["text_generation"]
                ),
                ProviderModelRegistration(
                    provider_id="openai", model_id="gpt-4o-mini", capabilities=["text_generation"]
                ),
            ]
        )
        router = ModelRouter(registry, health_checker=health)
        health.mark_cooldown("mock", seconds=60)

        decision = await router.route(router_request())

        assert decision.provider_id == "openai"
        assert decision.model_id == "gpt-4o-mini"

    asyncio.run(run_test())


def test_router_returns_unavailable_decision_when_all_filtered_by_health():
    async def run_test() -> None:
        settings = ProviderSettings(_env_file=None, openai_api_key="test-key")
        health = ProviderHealthChecker(settings)
        registry = RouterRegistry(
            [
                ProviderModelRegistration(
                    provider_id="mock", model_id="mock-model", capabilities=["text_generation"]
                ),
                ProviderModelRegistration(
                    provider_id="openai", model_id="gpt-4o-mini", capabilities=["text_generation"]
                ),
            ]
        )
        router = ModelRouter(registry, health_checker=health)
        health.mark_cooldown("mock", seconds=60)
        health.mark_cooldown("openai", seconds=60)

        decision = await router.route(router_request())

        assert decision.provider_id == ""
        assert "No registered provider is currently available" in decision.reasoning_summary

    asyncio.run(run_test())


# --- O8/O9: production composition and single routing implementation -------


def test_orchestrator_startup_allows_missing_keys_and_fails_at_execution(monkeypatch):
    """P0.3 — provider validation is decoupled from application construction.

    ``create_app``/``create_orchestrator`` must succeed without credentials so
    the application and /health stay reachable. Missing provider configuration
    surfaces as a clean execution-time error instead of a startup failure.
    """
    monkeypatch.setenv("SAMAKTHA_GROQ_API_KEY", "")
    monkeypatch.setenv("SAMAKTHA_OPENAI_API_KEY", "")
    monkeypatch.setenv("SAMAKTHA_OPENROUTER_API_KEY", "")
    monkeypatch.setenv("SAMAKTHA_LOCAL_BASE_URL", "")
    monkeypatch.setenv("SAMAKTHA_DEFAULT_PROVIDER", "groq")
    monkeypatch.setenv("SAMAKTHA_DEV_MODE", "false")
    monkeypatch.setenv("MOCK_AGENT", "")

    from fastapi.testclient import TestClient

    from app.config.settings import Settings
    from app.core.app import create_app, create_orchestrator
    from app.core.contracts import RuntimeContext

    orchestrator = create_orchestrator()
    assert orchestrator.provider_settings is not None

    async def run_test() -> None:
        with pytest.raises(ProviderStartupError, match="No production provider is configured"):
            await orchestrator.run(
                request="hello",
                runtime_context=RuntimeContext(request_id="req-1"),
            )

    asyncio.run(run_test())

    app = create_app(Settings())
    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200


def test_production_composition_never_registers_mock(monkeypatch):
    monkeypatch.setenv("SAMAKTHA_GROQ_API_KEY", "test-key")
    monkeypatch.setenv("SAMAKTHA_DEV_MODE", "false")
    monkeypatch.setenv("MOCK_AGENT", "")

    from app.core.app import create_orchestrator

    orchestrator = create_orchestrator()
    provider_ids = [info.provider_id for info in orchestrator.provider_registry.list_providers()]
    assert "mock" not in provider_ids
    assert "groq" in provider_ids


def test_production_composition_routes_through_shared_model_router(monkeypatch):
    monkeypatch.setenv("SAMAKTHA_GROQ_API_KEY", "test-key")
    monkeypatch.setenv("SAMAKTHA_DEV_MODE", "false")
    monkeypatch.setenv("MOCK_AGENT", "")

    from app.core.app import create_orchestrator

    orchestrator: SamakthaOrchestrator = create_orchestrator()
    assert isinstance(orchestrator._router, ModelRouter)
    assert orchestrator.health_checker is not None
    assert orchestrator.provider_manager is not None
    assert orchestrator._router._health_checker is orchestrator.health_checker


def test_dev_mode_composes_mock_provider(monkeypatch):
    monkeypatch.setenv("SAMAKTHA_DEV_MODE", "true")
    monkeypatch.setenv("SAMAKTHA_DEFAULT_PROVIDER", "mock")
    monkeypatch.setenv("SAMAKTHA_GROQ_API_KEY", "")

    from app.core.app import create_orchestrator

    orchestrator = create_orchestrator()
    provider_ids = [info.provider_id for info in orchestrator.provider_registry.list_providers()]
    assert "mock" in provider_ids
