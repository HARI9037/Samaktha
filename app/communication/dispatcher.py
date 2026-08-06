"""Phase 15 — Communication dispatcher.

Routes communication requests through the production runtime.
"""

from __future__ import annotations

import logging

from app.communication.models import CommunicationRequest, CommunicationResult
from app.communication.manager import CommunicationManager

log = logging.getLogger(__name__)


class CommunicationDispatcher:
    """Dispatches communication requests through the manager."""

    def __init__(self, manager: CommunicationManager) -> None:
        self._manager = manager

    async def dispatch(self, request: CommunicationRequest) -> CommunicationResult:
        """Dispatch a communication request."""
        return await self._manager.send(request)

    async def dispatch_batch(
        self, requests: list[CommunicationRequest]
    ) -> list[CommunicationResult]:
        """Dispatch multiple communication requests."""
        results = []
        for request in requests:
            result = await self.dispatch(request)
            results.append(result)
        return results

    def get_providers(self) -> list[str]:
        return self._manager.list_providers()

    def health_check(self) -> dict[str, bool]:
        return self._manager.health_check()