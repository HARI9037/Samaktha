from typing import Optional

from app.providers.health import ProviderHealthChecker
from app.providers.models import ProviderInfo
from app.providers.registry import ProviderRegistry


class ProviderSelectionEngine:
    """Deterministically selects configured providers from local metadata."""

    def __init__(
        self,
        registry: ProviderRegistry,
        health_checker: ProviderHealthChecker,
    ) -> None:
        self._registry = registry
        self._health_checker = health_checker

    def select_provider(
        self,
        required_capabilities: list[str],
        preferred_provider: str | None = None,
        preferred_model: str | None = None,
    ) -> Optional[ProviderInfo]:
        if preferred_provider is not None:
            preferred = self._provider_info(preferred_provider)
            if preferred is None:
                return None
            if self._is_available(preferred.provider_id):
                return preferred

        candidates = [
            provider
            for provider in self._registry.list_providers()
            if self._is_available(provider.provider_id)
        ]
        candidates = [
            provider
            for provider in candidates
            if self._supports_capabilities(provider, required_capabilities)
        ]

        if preferred_model is not None:
            model_matches = [
                provider
                for provider in candidates
                if preferred_model in self._supported_models(provider)
            ]
            if model_matches:
                candidates = model_matches

        return candidates[0] if candidates else None

    def _provider_info(self, provider_id: str) -> Optional[ProviderInfo]:
        return next(
            (
                provider
                for provider in self._registry.list_providers()
                if provider.provider_id == provider_id
            ),
            None,
        )

    def _is_available(self, provider_id: str) -> bool:
        return self._health_checker.check(
            provider_id=provider_id,
            provider=self._registry.get_provider(provider_id),
        ).available

    @staticmethod
    def _supports_capabilities(
        provider: ProviderInfo,
        required_capabilities: list[str],
    ) -> bool:
        return set(required_capabilities).issubset(set(provider.capabilities))

    @staticmethod
    def _supported_models(provider: ProviderInfo) -> list[str]:
        return provider.supported_models or provider.models
