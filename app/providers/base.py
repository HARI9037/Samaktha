from abc import ABC, abstractmethod
from typing import Any, AsyncIterator


class Provider(ABC):
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
