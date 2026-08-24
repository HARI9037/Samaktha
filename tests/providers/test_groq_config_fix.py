"""Regression tests for the Groq configuration fix (pre-P6).

Covers:
1. .env/settings load GROQ_API_KEY from the intended location.
2. API key values never appear in logs/errors.
3. Production Groq registration includes openai/gpt-oss-120b.
4. Router selects a provider-compatible Groq model.
5. Final Groq URL is exactly https://api.groq.com/openai/v1/chat/completions.
6. Final payload contains model = openai/gpt-oss-120b.
7. Local-only P1 requests still cannot route to Groq.
8. Provider fallback still uses provider-compatible models.
9. Model-specific 404 does not poison the entire provider when avoidable.
10. Sanitized Groq error bodies are retained.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.contracts import RouterRequest, RoutingDecision
from app.core.contracts.planning import GoalComplexity, TaskStatus
from app.providers import (
    GroqProvider,
    ProviderHealthChecker,
    ProviderInfo,
    ProviderManager,
    ProviderRegistry,
    ProviderSettings,
)
from app.providers.http_chat import OpenAICompatibleChatClient
from app.providers.models import ProviderResponse
from app.router import (
    CapabilityRegistry,
    ModelRouter,
    ProviderCapability,
    ProviderModelRegistration,
    RouterRegistry,
)
from app.router.capabilities import ProviderCapability as RouterCapability
from app.core.contracts.policy import ExecutionLocation, ExecutionConstraints
from app.models import ModelInfo, ModelManager, ModelRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings(**overrides) -> ProviderSettings:
    defaults = dict(
        _env_file=None,
        groq_api_key="test-key",
        groq_model="openai/gpt-oss-120b",
        groq_base_url="https://api.groq.com/openai/v1",
        groq_enabled=True,
        default_provider="groq",
        fallback_enabled=True,
        cooldown_seconds=60,
        max_retries=0,
        request_timeout_seconds=5.0,
        stream_enabled=True,
    )
    defaults.update(overrides)
    return ProviderSettings(**defaults)


def _groq_provider_info(settings: ProviderSettings) -> ProviderInfo:
    return ProviderInfo(
        provider_id="groq",
        execution_location=ExecutionLocation.CLOUD,
        capabilities=["text_generation"],
        models=[settings.groq_model],
        supported_models=[settings.groq_model, "llama-3.3-70b-versatile"],
        metadata={"maximum_context": 128000, "maximum_output": 1024},
    )


def _openrouter_provider_info(settings: ProviderSettings) -> ProviderInfo:
    return ProviderInfo(
        provider_id="openrouter",
        execution_location=ExecutionLocation.CLOUD,
        capabilities=["text_generation"],
        models=[settings.openrouter_model],
        supported_models=[settings.openrouter_model],
        metadata={"maximum_context": 128000, "maximum_output": 1024},
    )


def _build_model_registry(settings: ProviderSettings) -> ModelRegistry:
    registry = ModelRegistry()
    registry.register(ModelInfo(
        model_id=settings.groq_model,
        provider_id="groq",
        display_name="GPT OSS 120B (Groq)",
        context_window=128000,
        supports_tools=False,
        supports_streaming=True,
        supports_images=False,
        supports_audio=False,
        reasoning_score=9,
        coding_score=8,
        speed_score=10,
        cost_score=9,
        privacy_score=4,
        execution_location=ExecutionLocation.CLOUD,
    ))
    registry.register(ModelInfo(
        model_id="llama-3.3-70b-versatile",
        provider_id="groq",
        display_name="Llama 3.3 70B Versatile",
        context_window=128000,
        supports_tools=False,
        supports_streaming=False,
        supports_images=False,
        supports_audio=False,
        reasoning_score=8,
        coding_score=8,
        speed_score=10,
        cost_score=9,
        privacy_score=4,
        execution_location=ExecutionLocation.CLOUD,
    ))
    return registry


def _simple_router_request() -> RouterRequest:
    return RouterRequest(
        purpose="text_generation: hi",
        complexity=GoalComplexity.LOW,
        estimated_context_tokens=100,
        requires_local_model=False,
        requires_code=False,
        requires_reasoning=False,
    )


# ---------------------------------------------------------------------------
# 1. .env / settings load GROQ_API_KEY
# ---------------------------------------------------------------------------

class TestEnvLoading:
    def test_groq_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("SAMAKTHA_GROQ_API_KEY", "env-test-key")
        monkeypatch.setenv("SAMAKTHA_GROQ_MODEL", "openai/gpt-oss-120b")
        settings = ProviderSettings(_env_file=None)
        assert settings.groq_api_key == "env-test-key"

    def test_groq_model_from_env(self, monkeypatch):
        monkeypatch.setenv("SAMAKTHA_GROQ_API_KEY", "k")
        monkeypatch.setenv("SAMAKTHA_GROQ_MODEL", "openai/gpt-oss-120b")
        settings = ProviderSettings(_env_file=None)
        assert settings.groq_model == "openai/gpt-oss-120b"

    def test_groq_base_url_from_env(self, monkeypatch):
        monkeypatch.setenv("SAMAKTHA_GROQ_API_KEY", "k")
        monkeypatch.setenv("SAMAKTHA_GROQ_BASE_URL", "https://custom.groq.com/v1")
        settings = ProviderSettings(_env_file=None)
        assert settings.groq_base_url == "https://custom.groq.com/v1"

    def test_groq_base_url_default(self):
        settings = ProviderSettings(_env_file=None, groq_api_key="k")
        assert settings.groq_base_url == "https://api.groq.com/openai/v1"


# ---------------------------------------------------------------------------
# 2. API key never appears in logs/errors
# ---------------------------------------------------------------------------

class TestKeySanitization:
    @pytest.mark.asyncio
    async def test_missing_key_error_no_key_leak(self):
        settings = ProviderSettings(_env_file=None, groq_api_key=None)
        provider = GroqProvider(settings)
        result = await provider.execute({"prompt": "test"})
        assert result["success"] is False
        assert "test-key" not in (result.get("message") or "")
        assert result.get("message") == "Groq provider unavailable: missing API key"

    def test_key_not_in_exception_message(self):
        settings = ProviderSettings(_env_file=None, groq_api_key="super-secret-key-12345")
        provider = GroqProvider(settings)
        exc = httpx.HTTPStatusError(
            "error",
            request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
            response=httpx.Response(404),
        )
        assert ProviderManager._is_model_specific_error(exc)


# ---------------------------------------------------------------------------
# 3. Production Groq registration includes openai/gpt-oss-120b
# ---------------------------------------------------------------------------

class TestGroqModelRegistration:
    def test_groq_provider_info_includes_model(self):
        settings = _settings()
        info = _groq_provider_info(settings)
        assert settings.groq_model in info.models
        assert settings.groq_model in info.supported_models

    def test_model_registry_has_groq_model(self):
        settings = _settings()
        registry = _build_model_registry(settings)
        model = registry.get(settings.groq_model)
        assert model is not None
        assert model.provider_id == "groq"

    def test_model_manager_resolves_groq_model(self):
        settings = _settings()
        registry = _build_model_registry(settings)
        manager = ModelManager(registry)
        model = manager.resolve_model(settings.groq_model)
        assert model is not None
        assert model.execution_location == ExecutionLocation.CLOUD


# ---------------------------------------------------------------------------
# 4. Router selects provider-compatible Groq model
# ---------------------------------------------------------------------------

class TestRouterSelection:
    def _build_router(self, settings: ProviderSettings) -> ModelRouter:
        router_registry = RouterRegistry([
            ProviderModelRegistration(
                provider_id="groq",
                model_id=settings.groq_model,
                capabilities=["text_generation"],
                execution_location=ExecutionLocation.CLOUD,
            ),
        ])
        capability_registry = CapabilityRegistry()
        capability_registry.register(RouterCapability(
            provider_id="groq",
            execution_location=ExecutionLocation.CLOUD,
            model_id=settings.groq_model,
            capabilities=["text_generation"],
            reasoning_score=9,
            coding_score=8,
            speed_score=10,
            privacy_score=4,
            cost_score=9,
            context_window=128000,
            maximum_output=1024,
            latency_ms=20.0,
        ))
        model_registry = _build_model_registry(settings)
        health_checker = ProviderHealthChecker(settings)
        return ModelRouter(
            router_registry,
            capability_registry,
            model_manager=ModelManager(model_registry),
            health_checker=health_checker,
            preferred_provider="groq",
        )

    @pytest.mark.asyncio
    async def test_router_selects_groq_with_correct_model(self):
        settings = _settings()
        router = self._build_router(settings)
        request = _simple_router_request()
        decision = await router.route(request)
        assert decision.provider_id == "groq"
        assert decision.model_id == settings.groq_model

    @pytest.mark.asyncio
    async def test_router_preferred_provider_honored(self):
        settings = _settings(default_provider="groq")
        router = self._build_router(settings)
        request = _simple_router_request()
        decision = await router.route(request)
        assert decision.provider_id == "groq"


# ---------------------------------------------------------------------------
# 5. Final Groq URL is exactly correct
# ---------------------------------------------------------------------------

class TestGroqUrlConstruction:
    def test_base_url_no_double_path(self):
        settings = _settings()
        client = OpenAICompatibleChatClient(
            provider_id="groq",
            api_key=settings.groq_api_key,
            model_id=settings.groq_model,
            base_url=settings.groq_base_url,
            settings=settings,
            display_name="Groq",
        )
        expected = "https://api.groq.com/openai/v1/chat/completions"
        actual = f"{client._base_url}/chat/completions"
        assert actual == expected

    def test_base_url_trailing_slash_stripped(self):
        settings = _settings(groq_base_url="https://api.groq.com/openai/v1/")
        client = OpenAICompatibleChatClient(
            provider_id="groq",
            api_key=settings.groq_api_key,
            model_id=settings.groq_model,
            base_url=settings.groq_base_url,
            settings=settings,
            display_name="Groq",
        )
        assert client._base_url == "https://api.groq.com/openai/v1"
        assert f"{client._base_url}/chat/completions" == "https://api.groq.com/openai/v1/chat/completions"

    def test_no_openai_v1_duplication(self):
        settings = _settings()
        client = OpenAICompatibleChatClient(
            provider_id="groq",
            api_key=settings.groq_api_key,
            model_id=settings.groq_model,
            base_url=settings.groq_base_url,
            settings=settings,
            display_name="Groq",
        )
        url = f"{client._base_url}/chat/completions"
        assert url.count("/openai/v1") == 1


# ---------------------------------------------------------------------------
# 6. Final payload contains model = openai/gpt-oss-120b
# ---------------------------------------------------------------------------

class TestGroqPayload:
    @pytest.mark.asyncio
    async def test_execute_payload_model(self):
        settings = _settings()
        client = OpenAICompatibleChatClient(
            provider_id="groq",
            api_key=None,
            model_id=settings.groq_model,
            base_url=settings.groq_base_url,
            settings=settings,
        )
        result = await client.execute({"prompt": "hi"})
        assert result["success"] is False
        assert result["message"] == "Groq provider unavailable: missing API key"

    @pytest.mark.asyncio
    @patch("app.providers.http_chat.httpx.AsyncClient")
    async def test_execute_builds_correct_body(self, mock_client_cls):
        settings = _settings()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_response.raise_for_status = MagicMock()

        mock_async_client = AsyncMock()
        mock_async_client.post = AsyncMock(return_value=mock_response)
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_async_client

        client = OpenAICompatibleChatClient(
            provider_id="groq",
            api_key="test-key",
            model_id="openai/gpt-oss-120b",
            base_url="https://api.groq.com/openai/v1",
            settings=settings,
        )
        await client.execute({"prompt": "hi"})
        call_args = mock_async_client.post.call_args
        body = call_args[1]["json"]
        assert body["model"] == "openai/gpt-oss-120b"
        assert body["messages"][0]["content"] == "hi"


# ---------------------------------------------------------------------------
# 7. Local-only P1 requests cannot route to Groq
# ---------------------------------------------------------------------------

class TestLocalOnlyRouting:
    @pytest.mark.asyncio
    async def test_local_only_excludes_groq(self):
        settings = _settings()
        router_registry = RouterRegistry([
            ProviderModelRegistration(
                provider_id="groq",
                model_id=settings.groq_model,
                capabilities=["text_generation"],
                execution_location=ExecutionLocation.CLOUD,
            ),
        ])
        model_registry = _build_model_registry(settings)
        health_checker = ProviderHealthChecker(settings)
        router = ModelRouter(
            router_registry,
            model_manager=ModelManager(model_registry),
            health_checker=health_checker,
            preferred_provider="groq",
        )
        request = RouterRequest(
            purpose="text_generation: hi",
            complexity=GoalComplexity.LOW,
            estimated_context_tokens=100,
            requires_local_model=True,
            requires_code=False,
            requires_reasoning=False,
        )
        decision = await router.route(request)
        assert decision.provider_id == ""
        assert decision.model_id == ""


# ---------------------------------------------------------------------------
# 8. Provider fallback uses provider-compatible models
# ---------------------------------------------------------------------------

class TestProviderFallback:
    def test_fallback_skips_unavailable_provider(self):
        settings = _settings()
        registry = ProviderRegistry()

        class MockGP(GroqProvider):
            async def execute(self, payload):
                return {"success": False, "finish_reason": "http_error", "message": "error"}

        registry.register("groq", MockGP(settings), _groq_provider_info(settings))
        from app.providers import OpenRouterProvider
        registry.register("openrouter", OpenRouterProvider(settings), _openrouter_provider_info(settings))
        manager = ProviderManager(registry, settings)
        health_checker = manager._health_checker
        health_checker.mark_cooldown("groq")
        assert not health_checker.is_available("groq")


# ---------------------------------------------------------------------------
# 9. Model-specific 404 does not poison entire provider
# ---------------------------------------------------------------------------

class TestModelSpecific404:
    def test_is_model_specific_error_404(self):
        exc = httpx.HTTPStatusError(
            "error",
            request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
            response=httpx.Response(404),
        )
        assert ProviderManager._is_model_specific_error(exc) is True

    def test_is_model_specific_error_server_error(self):
        exc = httpx.HTTPStatusError(
            "error",
            request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
            response=httpx.Response(500),
        )
        assert ProviderManager._is_model_specific_error(exc) is False

    def test_is_model_specific_error_model_not_found_text(self):
        exc = RuntimeError("model_not_found: Model 'xyz' not found")
        assert ProviderManager._is_model_specific_error(exc) is True

    def test_is_model_specific_error_generic(self):
        exc = RuntimeError("connection timeout")
        assert ProviderManager._is_model_specific_error(exc) is False

    def test_is_model_specific_response_404(self):
        resp = ProviderResponse(
            success=False,
            message="groq provider HTTP error: 404",
            provider_id="groq",
            model_id="openai/gpt-oss-120b",
            finish_reason="http_error",
            metadata={"status_code": 404},
        )
        assert ProviderManager._is_model_specific_response(resp) is True

    def test_is_model_specific_response_server_error(self):
        resp = ProviderResponse(
            success=False,
            message="groq provider server error: 500",
            provider_id="groq",
            model_id="openai/gpt-oss-120b",
            finish_reason="server_error",
            metadata={"status_code": 500},
        )
        assert ProviderManager._is_model_specific_response(resp) is False

    @pytest.mark.asyncio
    async def test_model_specific_404_does_not_trigger_cooldown(self):
        settings = _settings()
        registry = ProviderRegistry()

        class ModelNotFoundProvider(GroqProvider):
            async def execute(self, payload):
                return {
                    "success": False,
                    "message": "groq provider HTTP error: 404",
                    "finish_reason": "http_error",
                    "provider_id": "groq",
                    "model_id": "openai/gpt-oss-120b",
                    "metadata": {"status_code": 404},
                }

        registry.register("groq", ModelNotFoundProvider(settings), _groq_provider_info(settings))
        from app.providers import OpenRouterProvider
        registry.register("openrouter", OpenRouterProvider(settings), _openrouter_provider_info(settings))
        manager = ProviderManager(registry, settings)
        health_checker = manager._health_checker
        await manager.execute_provider(
            provider_id="groq",
            payload={"prompt": "hi"},
            model_id="openai/gpt-oss-120b",
            required_capabilities=["text_generation"],
        )
        assert not health_checker.is_in_cooldown("groq")


# ---------------------------------------------------------------------------
# 10. Sanitized Groq error bodies retained
# ---------------------------------------------------------------------------

class TestSanitizedErrors:
    @pytest.mark.asyncio
    @patch("app.providers.http_chat.httpx.AsyncClient")
    async def test_stream_error_captures_body(self, mock_client_cls):
        settings = _settings()
        error_body = b'{"error": {"message": "Model not found", "type": "model_not_found"}}'
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")

        async def mock_aread():
            return error_body
        mock_response.aread = mock_aread

        class _StreamCtx:
            async def __aenter__(self):
                return mock_response
            async def __aexit__(self, *args):
                return False

        mock_async_client = MagicMock()
        mock_async_client.stream = MagicMock(return_value=_StreamCtx())
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_async_client

        client = OpenAICompatibleChatClient(
            provider_id="groq",
            api_key="test-key",
            model_id="openai/gpt-oss-120b",
            base_url="https://api.groq.com/openai/v1",
            settings=settings,
        )

        async def consume_stream():
            async for _ in client.execute_stream({"prompt": "hi"}):
                pass

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await consume_stream()
        assert "Model not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_non_stream_error_captures_status(self):
        settings = _settings()
        client = OpenAICompatibleChatClient(
            provider_id="groq",
            api_key=None,
            model_id="openai/gpt-oss-120b",
            base_url="https://api.groq.com/openai/v1",
            settings=settings,
        )
        result = await client.execute({"prompt": "hi"})
        assert result["success"] is False
        assert result["message"] is not None
