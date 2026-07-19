from typing import Any

from app.providers.base import Provider
from app.providers.config import ProviderSettings
from app.providers.http_chat import OpenAICompatibleChatClient


class GroqProvider(Provider):
    """Provider implementation for Groq cloud inference APIs."""

    def __init__(self, settings: ProviderSettings) -> None:
        self._settings = settings
        self._client = OpenAICompatibleChatClient(
            provider_id=self.name,
            api_key=settings.groq_api_key,
            model_id=settings.groq_model,
            base_url="https://api.groq.com/openai/v1",
            settings=settings,
            display_name="Groq",
        )

    @property
    def name(self) -> str:
        return "groq"

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._client.execute(payload)

    async def execute_stream(self, payload: dict[str, Any]):
        async for chunk in self._client.execute_stream(payload):
            yield chunk
