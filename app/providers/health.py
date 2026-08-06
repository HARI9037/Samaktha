import threading
from datetime import datetime, timedelta, timezone
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
    cooldown_until: datetime | None = None
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
        self._cooldowns: Dict[str, datetime] = {}
        self._lock = threading.Lock()

    def get_status(self, provider_id: str) -> ProviderStatus | None:
        with self._lock:
            return self._status_cache.get(provider_id)

    def is_available(self, provider_id: str) -> bool:
        """Availability without requiring a provider instance.

        Used by the Router so health and cooldown participate in selection.
        Uses cached status when present, otherwise a cheap config + cooldown
        check (never a network call).
        """
        status = self.get_status(provider_id)
        if status is not None:
            return status.available
        return (
            self._is_enabled(provider_id)
            and self._is_configured(provider_id)
            and not self.is_in_cooldown(provider_id)
        )

    def mark_cooldown(self, provider_id: str, seconds: Optional[int] = None) -> None:
        """Put a provider into cooldown so selection skips it."""
        seconds = seconds if seconds is not None else self._settings.cooldown_seconds
        with self._lock:
            self._cooldowns[provider_id] = datetime.now(timezone.utc) + timedelta(
                seconds=seconds,
            )

    def clear_cooldown(self, provider_id: str) -> None:
        with self._lock:
            self._cooldowns.pop(provider_id, None)

    def is_in_cooldown(self, provider_id: str) -> bool:
        with self._lock:
            until = self._cooldowns.get(provider_id)
            if until is None:
                return False
            if until <= datetime.now(timezone.utc):
                self._cooldowns.pop(provider_id, None)
                return False
            return True

    def cooldown_until(self, provider_id: str) -> datetime | None:
        with self._lock:
            until = self._cooldowns.get(provider_id)
            if until is None:
                return None
            if until <= datetime.now(timezone.utc):
                self._cooldowns.pop(provider_id, None)
                return None
            return until

    def cooldown_providers(self) -> list[str]:
        """Provider ids currently in cooldown (with active timers)."""
        with self._lock:
            now = datetime.now(timezone.utc)
            expired = [
                provider_id
                for provider_id, until in self._cooldowns.items()
                if until <= now
            ]
            for provider_id in expired:
                self._cooldowns.pop(provider_id, None)
            return [
                provider_id
                for provider_id, until in self._cooldowns.items()
                if until > now
            ]

    def check(
        self,
        provider_id: str,
        provider: Optional[BaseProvider],
    ) -> ProviderStatus:
        """Inspect and return the current health status for a provider.

        This is a lightweight, synchronous check against cached state and
        local configuration — it does NOT make network calls. Cooldown is a
        hard availability gate: a provider in cooldown is never available.
        """
        enabled = self._is_enabled(provider_id)
        configured = provider is not None and self._is_configured(provider_id)
        in_cooldown = self.is_in_cooldown(provider_id)
        available = enabled and configured and not in_cooldown

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
        if in_cooldown and last_error is None:
            last_error = "Provider is in cooldown"
        if not reachable and last_error is None:
            last_error = "Provider is currently unreachable"

        with self._lock:
            existing = self._status_cache.get(provider_id)
            if existing:
                existing.enabled = enabled
                existing.configured = configured
                existing.available = available
                existing.rate_limited = in_cooldown
                existing.cooldown_until = self._cooldowns.get(provider_id)
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
                rate_limited=in_cooldown,
                cooldown_until=self._cooldowns.get(provider_id),
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
