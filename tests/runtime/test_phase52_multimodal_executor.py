"""Phase 5.2 tests — MultimodalExecutor.

Validates:
- Multimodal requests route through ProviderManager (not directly to providers)
- Provider boundary is preserved
- Metrics are recorded
- Invalid media type is caught
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.contracts.multimodal import MediaInput, MediaType, MultimodalRequest
from app.runtime.multimodal import MultimodalExecutor
from app.runtime.multimodal_metrics import MultimodalMetricsCollector


def _make_provider_manager(response: dict) -> MagicMock:
    """Build a mock ProviderManager that returns the given response dict."""
    mgr = MagicMock()
    mgr.execute_provider = AsyncMock(return_value=response)
    return mgr


@pytest.mark.asyncio
async def test_multimodal_executor_uses_provider_manager():
    """Multimodal execution must go through ProviderManager, not directly to a provider."""
    manager = _make_provider_manager({
        "content": "A photo of a cat sitting on a mat.",
        "detected_items": ["cat", "mat"],
        "usage": {"tokens": 42},
    })

    executor = MultimodalExecutor(provider_manager=manager)
    request = MultimodalRequest(
        input=MediaInput(
            media_id="img-001",
            media_type=MediaType.IMAGE,
            source="https://example.com/cat.jpg",
        ),
        instructions="Describe the image",
    )

    response = await executor.execute(request, provider_id="vision_provider")

    # ProviderManager must have been called exactly once
    manager.execute_provider.assert_awaited_once()
    call_kwargs = manager.execute_provider.call_args

    # Must be routed through ProviderManager
    assert call_kwargs.kwargs["provider_id"] == "vision_provider"
    assert response.content == "A photo of a cat sitting on a mat."
    assert "cat" in response.detected_items


@pytest.mark.asyncio
async def test_multimodal_executor_returns_correct_response():
    manager = _make_provider_manager({
        "content": "Audio transcript: Hello world.",
        "usage": {"tokens": 5},
    })
    executor = MultimodalExecutor(provider_manager=manager)
    request = MultimodalRequest(
        input=MediaInput(
            media_id="audio-001",
            media_type=MediaType.AUDIO,
            source="https://example.com/speech.mp3",
        ),
        instructions="Transcribe audio",
    )

    response = await executor.execute(request, provider_id="audio_provider")
    assert "Hello world" in response.content
    assert response.provider_id == "audio_provider"


@pytest.mark.asyncio
async def test_multimodal_executor_records_metrics():
    manager = _make_provider_manager({"content": "ok"})
    metrics = MultimodalMetricsCollector()
    executor = MultimodalExecutor(provider_manager=manager, metrics=metrics)

    request = MultimodalRequest(
        input=MediaInput(
            media_id="doc-001",
            media_type=MediaType.DOCUMENT,
            source="https://example.com/report.pdf",
        ),
    )

    await executor.execute(request, provider_id="doc_provider")

    snapshot = metrics.get_snapshot()
    assert snapshot["counts"][MediaType.DOCUMENT.value] == 1
    assert snapshot["failures"][MediaType.DOCUMENT.value] == 0


@pytest.mark.asyncio
async def test_multimodal_executor_records_failure_on_error():
    manager = MagicMock()
    manager.execute_provider = AsyncMock(side_effect=Exception("Provider timeout"))
    metrics = MultimodalMetricsCollector()
    executor = MultimodalExecutor(provider_manager=manager, metrics=metrics)

    request = MultimodalRequest(
        input=MediaInput(
            media_id="img-002",
            media_type=MediaType.IMAGE,
            source="https://example.com/fail.jpg",
        ),
    )

    with pytest.raises(RuntimeError, match="Multimodal execution failed"):
        await executor.execute(request, provider_id="bad_provider")

    snapshot = metrics.get_snapshot()
    assert snapshot["failures"][MediaType.IMAGE.value] == 1
