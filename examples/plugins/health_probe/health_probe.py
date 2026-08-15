"""Health Probe — example Samaktha provider plugin.

A deterministic ``CommunicationProvider`` for smoke tests: healthy, never
touches the network, and records everything it would deliver. See
docs/PLUGINS.md for the plugin author guide.
"""

from __future__ import annotations

from app.communication.models import (
    CommunicationProvider as CommunicationProviderEnum,
    CommunicationRequest,
    CommunicationResult,
    CommunicationStatus,
)
from app.communication.provider import CommunicationProvider
from app.plugins import Plugin
from app.plugins.models import PluginManifest


class HealthProbeProvider(CommunicationProvider):
    provider_id = "health_probe"

    def __init__(self) -> None:
        self.delivered: list[CommunicationRequest] = []

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        pass

    async def send(self, request: CommunicationRequest) -> CommunicationResult:
        self.delivered.append(request)
        return CommunicationResult(
            status=CommunicationStatus.SENT,
            provider=CommunicationProviderEnum.TEST,
            message_id="health-probe-1",
        )

    async def receive(self, limit: int = 10) -> list[CommunicationResult]:
        return []

    async def health(self) -> bool:
        return True

    async def validate(self, request: CommunicationRequest) -> list[str]:
        errors = []
        if not request.recipient:
            errors.append("recipient is required")
        return errors


MANIFEST = PluginManifest(
    id="health_probe",
    name="Health Probe Example Provider",
    version="1.0.0",
    kind="provider",
    description="Example provider: a deterministic communication provider for smoke tests.",
    author="Samaktha Team",
    entry="health_probe",
)


class HealthProbePlugin(Plugin):
    @property
    def manifest(self):
        return MANIFEST

    def provide_providers(self):
        return [HealthProbeProvider()]


def create_plugin():
    return HealthProbePlugin()
