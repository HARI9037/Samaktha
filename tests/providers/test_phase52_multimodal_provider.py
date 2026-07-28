"""Phase 5.2 tests — Multimodal Provider Integration.

Validates:
- Vision provider accepted (supports VISION capability)
- Text-only provider rejected (does not implement process_multimodal)
- Capability validation at execution boundary
"""
import pytest

from app.core.contracts.multimodal import MediaInput, MediaType, MultimodalRequest, MultimodalResponse
from app.core.contracts.provider import ProviderCapability
from app.providers.base import BaseProvider


class VisionMockProvider(BaseProvider):
    """Test provider that declares VISION capability."""

    @property
    def name(self) -> str:
        return "vision_mock"

    async def execute(self, payload: dict) -> dict:
        return {"response": "text only"}

    def supports(self, capability: ProviderCapability) -> bool:
        return capability in (ProviderCapability.VISION, ProviderCapability.TEXT_GENERATION)

    async def health_check(self) -> bool:
        return True

    async def process_multimodal(self, request: MultimodalRequest) -> MultimodalResponse:
        return MultimodalResponse(
            content="Detected: cat, dog",
            detected_items=["cat", "dog"],
            provider_id=self.name,
            usage={"tokens": 10},
        )


class TextOnlyMockProvider(BaseProvider):
    """Test provider that only supports TEXT_GENERATION — no multimodal."""

    @property
    def name(self) -> str:
        return "text_only_mock"

    async def execute(self, payload: dict) -> dict:
        return {"response": "text"}

    def supports(self, capability: ProviderCapability) -> bool:
        return capability == ProviderCapability.TEXT_GENERATION

    async def health_check(self) -> bool:
        return True

    # Does NOT override process_multimodal — inherits the NotImplementedError default


def test_vision_provider_declares_capability():
    provider = VisionMockProvider()
    assert provider.supports(ProviderCapability.VISION) is True


def test_text_only_provider_rejects_vision_capability():
    provider = TextOnlyMockProvider()
    assert provider.supports(ProviderCapability.VISION) is False


@pytest.mark.asyncio
async def test_vision_provider_process_multimodal():
    provider = VisionMockProvider()
    request = MultimodalRequest(
        input=MediaInput(
            media_id="img-001",
            media_type=MediaType.IMAGE,
            source="https://example.com/cat.jpg",
        ),
        instructions="Describe the image",
    )
    response = await provider.process_multimodal(request)
    assert response.content == "Detected: cat, dog"
    assert "cat" in response.detected_items
    assert response.provider_id == "vision_mock"


@pytest.mark.asyncio
async def test_text_only_provider_raises_on_multimodal():
    provider = TextOnlyMockProvider()
    request = MultimodalRequest(
        input=MediaInput(
            media_id="img-002",
            media_type=MediaType.IMAGE,
            source="https://example.com/dog.jpg",
        ),
    )
    with pytest.raises(NotImplementedError, match="does not support multimodal"):
        await provider.process_multimodal(request)


def test_capability_validation_vision_vs_audio():
    provider = VisionMockProvider()
    assert provider.supports(ProviderCapability.AUDIO) is False
