"""Phase 15 — Communication manager.

Manages communication lifecycle through the production runtime.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.communication.models import (
    CommunicationRequest,
    CommunicationResult,
    CommunicationStatus,
)
from app.communication.provider import CommunicationProvider
from app.communication.registry import CommunicationRegistry

log = logging.getLogger(__name__)


class CommunicationManager:
    """Manages communication through the production runtime pipeline.

    All outbound communication goes through CAP governance.
    This manager only orchestrates; it does not bypass any layer.
    """

    def __init__(self, registry: CommunicationRegistry | None = None) -> None:
        self._registry = registry or CommunicationRegistry()

    def get_registry(self) -> CommunicationRegistry:
        return self._registry

    async def send(
        self,
        request: CommunicationRequest,
    ) -> CommunicationResult:
        """Send a communication request through the provider."""
        provider = self._registry.get_provider(request.provider.value)
        if provider is None:
            return CommunicationResult(
                status=CommunicationStatus.FAILED,
                provider=request.provider,
                errors=[f"Provider {request.provider.value} not registered"],
            )

        validation_errors = await provider.validate(request)
        if validation_errors:
            return CommunicationResult(
                status=CommunicationStatus.FAILED,
                provider=request.provider,
                errors=validation_errors,
            )

        try:
            result = await provider.send(request)
            return result
        except Exception as exc:
            log.error("Communication send failed: %s", exc)
            return CommunicationResult(
                status=CommunicationStatus.FAILED,
                provider=request.provider,
                errors=[str(exc)],
            )

    async def health_check(self) -> dict[str, bool]:
        return self._registry.health_check()

    def list_providers(self) -> list[str]:
        return self._registry.list_providers()

    def has_provider(self, name: str) -> bool:
        return self._registry.has_provider(name)