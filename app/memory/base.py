from abc import ABC, abstractmethod
from typing import Any


class Memory(ABC):
    @abstractmethod
    async def read(self, key: str) -> Any | None:
        raise NotImplementedError

    @abstractmethod
    async def write(self, key: str, value: Any) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, key: str) -> None:
        raise NotImplementedError
