"""Phase 15 — Communication registry.

Manages communication provider registration and discovery.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from app.communication.models import CommunicationProvider
from app.communication.provider import (
    DesktopProvider,
    DiscordProvider,
    GmailProvider,
    OutlookProvider,
    PushProvider,
    SMSProvider,
    SlackProvider,
    SMTPProvider,
    TelegramProvider,
    TestProvider,
    WebhookProvider,
    WhatsAppProvider,
)


class CommunicationRegistry:
    """Registry of available communication providers."""

    def __init__(self) -> None:
        self._providers: dict[str, CommunicationProvider] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.register("smtp", SMTPProvider())
        self.register("gmail", GmailProvider())
        self.register("outlook", OutlookProvider())
        self.register("whatsapp", WhatsAppProvider())
        self.register("telegram", TelegramProvider())
        self.register("discord", DiscordProvider())
        self.register("slack", SlackProvider())
        self.register("sms", SMSProvider())
        self.register("webhook", WebhookProvider())
        self.register("push", PushProvider())
        self.register("desktop", DesktopProvider())
        self.register("test", TestProvider())

    def register(self, name: str, provider: CommunicationProvider) -> None:
        self._providers[name.lower()] = provider

    def unregister(self, name: str) -> bool:
        name_lower = name.lower()
        if name_lower in self._providers:
            del self._providers[name_lower]
            return True
        return False

    def get_provider(self, name: str) -> CommunicationProvider | None:
        return self._providers.get(name.lower())

    def has_provider(self, name: str) -> bool:
        return name.lower() in self._providers

    def list_providers(self) -> list[str]:
        return sorted(self._providers.keys())

    def find_by_capability(self, capability: str) -> list[str]:
        results = []
        for name, provider in self._providers.items():
            if hasattr(provider, capability):
                results.append(name)
        return results

    def health_check(self) -> dict[str, bool]:
        return {name: asyncio.run(provider.health()) for name, provider in self._providers.items()}

    def count(self) -> int:
        return len(self._providers)