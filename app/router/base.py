from abc import ABC, abstractmethod

from app.core.contracts import RouterRequest, RoutingDecision


class ProviderRouter(ABC):
    """Interface for routing model requests without selecting providers directly."""

    @abstractmethod
    async def route(self, request: RouterRequest) -> RoutingDecision:
        raise NotImplementedError


Router = ProviderRouter
