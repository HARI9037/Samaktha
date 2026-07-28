import threading
from datetime import datetime, timezone
from typing import Dict, Optional

from pydantic import BaseModel

from app.providers.base import BaseProvider
from app.providers.config import ProviderSettings


class ProviderStatus(BaseModel):
    """Current deterministic health state for a provider."""

    provider_id: str
    enabled: bool
    configured: bool
    available: bool
    reachable: bool = False
    rate_limited: bool = False
    last_checked: datetime | None = None
    last_error: str | None = None
    failures: int = 0
    total_latency_ms: float = 0.0
    successful_calls: int = 0
    last_successful_execution: datetime | None = None

    @property
    def average_latency(self) -> float:
        return self.total_latency_ms / self.successful_calls if self.successful_calls > 0 else 0.0


class ProviderHealthChecker:
    """Inspects and tracks provider availability and health.

    All methods are synchronous and thread-safe via a threading.Lock,
    making this class safe to call from both sync (manager.py) and
    async (runtime, router) code without event-loop conflicts.
    """

    def __init__(self, settings: Optional[ProviderSettings] = None) -> None:
        self._settings = settings or ProviderSettings()
        self._status_cache: Dict[str, ProviderStatus] = {}
        self._lock = threading.Lock()

    def get_status(self, provider_id: str) -> ProviderStatus | None:
        with self._lock:
            return self._status_cache.get(provider_id)

    def check(
        self,
        provider_id: str,
        provider: Optional[BaseProvider],
    ) -> ProviderStatus:
        """Inspect and return the current health status for a provider.

        This is a lightweight, synchronous check against cached state and
        local configuration — it does NOT make network calls.
        """
        enabled = self._is_enabled(provider_id)
        configured = provider is not None and self._is_configured(provider_id)
        available = enabled and configured

        reachable = False
        if available and provider is not None:
            # Use cached reachability; assume reachable if first time seen
            with self._lock:
                existing = self._status_cache.get(provider_id)
            reachable = existing.reachable if existing else True

        last_error = self._last_error(
            provider=provider,
            enabled=enabled,
            configured=configured,
        )
        if not reachable and last_error is None:
            last_error = "Provider is currently unreachable"

        with self._lock:
            existing = self._status_cache.get(provider_id)
            if existing:
                existing.enabled = enabled
                existing.configured = configured
                existing.available = available
                existing.last_checked = datetime.now(timezone.utc)
                if last_error:
                    existing.last_error = last_error
                return existing

            new_status = ProviderStatus(
                provider_id=provider_id,
                enabled=enabled,
                configured=configured,
                available=available,
                reachable=reachable,
                rate_limited=False,
                last_checked=datetime.now(timezone.utc),
                last_error=last_error,
            )
            self._status_cache[provider_id] = new_status
            return new_status

    def record_success(self, provider_id: str, latency_ms: float) -> None:
        """Record a successful execution for a provider."""
        with self._lock:
            if provider_id not in self._status_cache:
                self._status_cache[provider_id] = ProviderStatus(
                    provider_id=provider_id, enabled=True, configured=True, available=True
                )
            status = self._status_cache[provider_id]
            status.successful_calls += 1
            status.total_latency_ms += latency_ms
            status.last_successful_execution = datetime.now(timezone.utc)
            status.last_error = None
            status.reachable = True
            status.failures = 0

    def record_failure(self, provider_id: str, error_message: str) -> None:
        """Record a failure for a provider."""
        with self._lock:
            if provider_id not in self._status_cache:
                self._status_cache[provider_id] = ProviderStatus(
                    provider_id=provider_id, enabled=True, configured=True, available=True
                )
            status = self._status_cache[provider_id]
            status.failures += 1
            status.last_error = error_message
            status.reachable = False

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
        provider: Optional[BaseProvider],
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
