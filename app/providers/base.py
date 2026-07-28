from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, TYPE_CHECKING

from app.core.contracts.provider import ProviderCapability

if TYPE_CHECKING:
    from app.core.contracts.multimodal import MultimodalRequest, MultimodalResponse
    from app.core.contracts.streaming import StreamChunk, StreamRequest


class BaseProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    async def execute_stream(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        response = await self.execute(payload)
        content = response.get("content") or response.get("response") or ""
        if content:
            yield content

    async def stream(self, request: "StreamRequest") -> AsyncIterator["StreamChunk"]:
        """Stream a response incrementally as StreamChunks.
        
        Providers that support native streaming should override this method.
        The default implementation raises NotImplementedError.
        """
        raise NotImplementedError(
            f"Provider '{self.name}' does not support streaming via StreamRequest."
        )
        yield  # type: ignore # to make it an async generator

    @abstractmethod
    def supports(self, capability: ProviderCapability) -> bool:
        """Return True if this provider supports the given capability."""
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> bool:
        """Perform a basic health check for this provider."""
        raise NotImplementedError

    async def process_multimodal(
        self,
        request: "MultimodalRequest",
    ) -> "MultimodalResponse":
        """Process a multimodal request.

        Only providers that support VISION or AUDIO capabilities should
        override this method.  The default raises NotImplementedError so
        that callers can detect unsupported providers before dispatch.
        """
        raise NotImplementedError(
            f"Provider '{self.name}' does not support multimodal processing. "
            "Override process_multimodal() and declare VISION/AUDIO capability."
        )
