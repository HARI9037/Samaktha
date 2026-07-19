from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

from app.providers.base import Provider
from app.providers.config import ProviderSettings


class ProviderStatus(BaseModel):
    """Current deterministic health state for a provider."""

    provider_id: str
    enabled: bool
    configured: bool
    available: bool
    reachable: bool = False
    rate_limited: bool = False
    last_checked: datetime | None
    last_error: str | None


class ProviderHealthChecker:
    """Inspects provider availability from local configuration only."""

    def __init__(self, settings: Optional[ProviderSettings] = None) -> None:
        self._settings = settings or ProviderSettings()

    def check(
        self,
        provider_id: str,
        provider: Optional[Provider],
    ) -> ProviderStatus:
        enabled = self._is_enabled(provider_id)
        configured = provider is not None and self._is_configured(provider_id)
        available = enabled and configured
        last_error = self._last_error(
            provider=provider,
            enabled=enabled,
            configured=configured,
        )

        return ProviderStatus(
            provider_id=provider_id,
            enabled=enabled,
            configured=configured,
            available=available,
            reachable=False,
            rate_limited=False,
            last_checked=datetime.now(timezone.utc),
            last_error=last_error,
        )

    def _is_enabled(self, provider_id: str) -> bool:
        enabled_by_provider = {
            "mock": self._settings.mock_enabled,
            "openai": self._settings.openai_enabled,
            "groq": self._settings.groq_enabled,
            "openrouter": self._settings.openrouter_enabled,
            "local": self._settings.local_enabled,
        }
        return enabled_by_provider.get(provider_id, True)

    def _is_configured(self, provider_id: str) -> bool:
        configured_by_provider = {
            "mock": True,
            "openai": bool(self._settings.openai_api_key),
            "groq": bool(self._settings.groq_api_key),
            "openrouter": bool(self._settings.openrouter_api_key),
            "local": bool(self._settings.local_base_url),
        }
        return configured_by_provider.get(provider_id, True)

    @staticmethod
    def _last_error(
        provider: Optional[Provider],
        enabled: bool,
        configured: bool,
    ) -> str | None:
        if provider is None:
            return "Provider is not registered"
        if not enabled:
            return "Provider is disabled"
        if not configured:
            return "Provider configuration is incomplete"
        return None
