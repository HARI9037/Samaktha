from typing import Dict, List, Optional, Tuple

from app.core.contracts.provider import ProviderCapability
from app.providers.base import BaseProvider
from app.providers.models import ProviderInfo


class ProviderRegistry:
    """Stores available providers and their metadata."""

    def __init__(self) -> None:
        # Dictionary maintains insertion order in modern Python, satisfying deterministic ordering.
        self._providers: Dict[str, Tuple[BaseProvider, ProviderInfo]] = {}

    def register(self, provider_id: str, provider: BaseProvider, info: ProviderInfo) -> None:
        """Register a provider with its metadata."""
        self._providers[provider_id] = (provider, info)

    def remove(self, provider_id: str) -> bool:
        """Remove a provider from the registry. Returns True if removed."""
        if provider_id in self._providers:
            del self._providers[provider_id]
            return True
        return False

    def get_provider(self, provider_id: str) -> Optional[BaseProvider]:
        """Retrieve a provider by its ID."""
        entry = self._providers.get(provider_id)
        return entry[0] if entry else None

    def get_info(self, provider_id: str) -> Optional[ProviderInfo]:
        """Retrieve provider metadata by its ID."""
        entry = self._providers.get(provider_id)
        return entry[1] if entry else None

    def list_providers(self) -> List[ProviderInfo]:
        """List metadata for all registered providers."""
        return [entry[1] for entry in self._providers.values()]

    def find_by_capability(self, capability: ProviderCapability) -> List[ProviderInfo]:
        """Discover providers that support a specific capability."""
        return [
            info for provider, info in self._providers.values()
            if provider.supports(capability)
        ]

    def validate_availability(self) -> List[str]:
        """Validate which providers are registered."""
        return list(self._providers.keys())
