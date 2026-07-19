from abc import ABC, abstractmethod

from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeResult, RuntimeTask


class Runtime(ABC):
    @abstractmethod
    async def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def run(
        self,
        context: RuntimeContext,
        task: RuntimeTask,
        routing: RoutingDecision,
    ) -> RuntimeResult:
        raise NotImplementedError
