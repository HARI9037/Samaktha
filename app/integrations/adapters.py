"""P10.2 — Canonical Adapters."""

from typing import Any

from app.integrations.contracts import (
    IntegrationProvider,
    IntegrationRequest,
    IntegrationResult,
    IntegrationStatus,
)


class TestIntegrationProvider(IntegrationProvider):
    """Deterministic in-memory adapter for testing canonical integrations.

    Like TestProvider in communication, but bound to the Integration contracts.
    """

    __test__ = False

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        self.sent: list[IntegrationRequest] = []
        self._seq = 0
        self.is_connected = False

    async def connect(self) -> bool:
        self.is_connected = True
        return True

    async def disconnect(self) -> None:
        self.is_connected = False

    async def health(self) -> bool:
        return self.is_connected

    async def validate(self, request: IntegrationRequest) -> list[str]:
        if request.provider_id != self.provider_id:
            return [f"Provider mismatch: {request.provider_id} != {self.provider_id}"]
        return []

    async def execute(self, request: IntegrationRequest) -> IntegrationResult:
        errors = await self.validate(request)
        if errors:
            return IntegrationResult(
                status=IntegrationStatus.FAILED,
                provider_id=self.provider_id,
                delivery_status="failed",
                errors=errors,
            )

        self._seq += 1
        self.sent.append(request)

        return IntegrationResult(
            status=IntegrationStatus.DELIVERED,
            provider_id=self.provider_id,
            external_id=f"test-{self._seq}",
            delivery_status="delivered",
            metadata={"test_mode": True},
        )
