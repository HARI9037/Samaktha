from typing import Any

from app.core.contracts.provider import ProviderCapability
from app.providers.base import BaseProvider
from app.providers.config import ProviderSettings
from app.providers.http_chat import OpenAICompatibleChatClient


class OpenAIProvider(BaseProvider):
    """Provider implementation for OpenAI-compatible APIs."""

    def __init__(self, settings: ProviderSettings) -> None:
        self._settings = settings
        self._client = OpenAICompatibleChatClient(
            provider_id=self.name,
            api_key=settings.openai_api_key,
            model_id=settings.openai_model,
            base_url="https://api.openai.com/v1",
            settings=settings,
            display_name="OpenAI",
        )

    @property
    def name(self) -> str:
        return "openai"

    def supports(self, capability: ProviderCapability) -> bool:
        return capability == ProviderCapability.TEXT_GENERATION

    async def health_check(self) -> bool:
        return True

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._client.execute(payload)

    async def execute_stream(self, payload: dict[str, Any]):
        async for chunk in self._client.execute_stream(payload):
            yield chunk
