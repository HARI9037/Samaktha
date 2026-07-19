import pytest

from app.providers import (
    CostEstimator,
    MockProvider,
    OpenAIProvider,
    ProviderInfo,
    ProviderManager,
    ProviderRegistry,
    ProviderResponse,
    ProviderSettings,
    UsageTracker,
)


class SuccessfulProvider(MockProvider):
    @property
    def name(self) -> str:
        return "successful"

    async def execute(self, payload):
        return ProviderResponse(
            success=True,
            content="ok",
            provider_id=self.name,
            model_id=payload.get("model_id", "successful-model"),
            finish_reason="stop",
            usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            cost={"input_cost": 0.0, "output_cost": 0.0, "total_cost": 0.0},
            latency_ms=5.0,
        ).model_dump()


class RateLimitedProvider(MockProvider):
    @property
    def name(self) -> str:
        return "limited"

    async def execute(self, payload):
        return ProviderResponse(
            success=False,
            message="rate limited",
            provider_id=self.name,
            model_id=payload.get("model_id", "limited-model"),
            finish_reason="rate_limited",
        ).model_dump()


class StreamingProvider(SuccessfulProvider):
    async def execute_stream(self, payload):
        yield "hel"
        yield "lo"


def test_response_normalization_fields():
    response = ProviderResponse(
        success=True,
        content="hello",
        provider_id="openai",
        model_id="gpt-4o-mini",
        finish_reason="stop",
    )

    data = response.model_dump()

    assert data["success"] is True
    assert data["content"] == "hello"
    assert data["finish_reason"] == "stop"
    assert "usage" in data
    assert "cost" in data
    assert "latency_ms" in data


def test_cost_estimation():
    cost = CostEstimator().estimate(
        model="gpt-4o-mini",
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
    )

    assert cost.input_cost == 0.15
    assert cost.output_cost == 0.60
    assert cost.total_cost == 0.75


def test_usage_tracking():
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    usage = UsageTracker().track(
        provider="openai",
        model="gpt-4o-mini",
        prompt_tokens=3,
        completion_tokens=4,
        request_timestamp=now,
        response_timestamp=now,
    )

    assert usage.total_tokens == 7
    assert usage.provider == "openai"


@pytest.mark.asyncio
async def test_provider_manager_fallback():
    manager = _manager_with_limited_then_successful()

    result = await manager.execute_provider(
        provider_id="limited",
        payload={"prompt": "hello"},
        model_id="limited-model",
        required_capabilities=["text_generation"],
    )

    assert result["success"] is True
    assert result["provider_id"] == "successful"


@pytest.mark.asyncio
async def test_cooldown_after_rate_limit():
    manager = _manager_with_limited_then_successful()

    await manager.execute_provider(
        provider_id="limited",
        payload={"prompt": "hello"},
        model_id="limited-model",
        required_capabilities=["text_generation"],
    )

    status = manager.get_provider_status("limited")
    assert status.available is False
    assert status.rate_limited is True


@pytest.mark.asyncio
async def test_context_validation():
    registry = ProviderRegistry()
    registry.register(
        "successful",
        SuccessfulProvider(),
        ProviderInfo(
            provider_id="successful",
            capabilities=["text_generation"],
            models=["successful-model"],
            supported_models=["successful-model"],
            metadata={"maximum_context": 2},
        ),
    )
    manager = ProviderManager(registry, ProviderSettings(fallback_enabled=False))

    result = await manager.execute_provider(
        provider_id="successful",
        payload={"prompt": "this prompt is too long", "max_tokens": 1},
        model_id="successful-model",
        required_capabilities=["text_generation"],
    )

    assert result["success"] is False
    assert result["finish_reason"] == "context_window_exceeded"


@pytest.mark.asyncio
async def test_streaming_chunks():
    registry = ProviderRegistry()
    registry.register(
        "streaming",
        StreamingProvider(),
        ProviderInfo(
            provider_id="streaming",
            capabilities=["text_generation"],
            models=["streaming-model"],
            supported_models=["streaming-model"],
        ),
    )
    manager = ProviderManager(registry)

    chunks = [
        chunk
        async for chunk in manager.execute_provider_stream(
            provider_id="streaming",
            payload={"prompt": "hello"},
            model_id="streaming-model",
        )
    ]

    assert chunks == ["hel", "lo"]


def test_provider_metrics():
    manager = _manager_with_limited_then_successful()

    metrics = manager.get_provider_metrics("successful")

    assert metrics.provider_id == "successful"
    assert metrics.requests == 0


@pytest.mark.asyncio
async def test_openai_http_execution_with_mocked_client(monkeypatch):
    class FakeClient:
        async def execute(self, payload):
            return ProviderResponse(
                success=True,
                content="mocked http",
                provider_id="openai",
                model_id="gpt-4o-mini",
                finish_reason="stop",
            ).model_dump()

    provider = OpenAIProvider(ProviderSettings(openai_api_key="test-key"))
    monkeypatch.setattr(provider, "_client", FakeClient())

    result = await provider.execute({"prompt": "hello"})

    assert result["success"] is True
    assert result["content"] == "mocked http"
    assert result["provider_id"] == "openai"


def _manager_with_limited_then_successful() -> ProviderManager:
    registry = ProviderRegistry()
    registry.register(
        "limited",
        RateLimitedProvider(),
        ProviderInfo(
            provider_id="limited",
            capabilities=["text_generation"],
            models=["limited-model"],
            supported_models=["limited-model"],
        ),
    )
    registry.register(
        "successful",
        SuccessfulProvider(),
        ProviderInfo(
            provider_id="successful",
            capabilities=["text_generation"],
            models=["successful-model"],
            supported_models=["successful-model"],
        ),
    )
    return ProviderManager(registry, ProviderSettings())
