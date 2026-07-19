from typing import Dict, List, Optional, Tuple

from app.providers.base import Provider
from app.providers.models import ProviderInfo


class ProviderRegistry:
    """Stores available providers and their metadata."""

    def __init__(self) -> None:
        self._providers: Dict[str, Tuple[Provider, ProviderInfo]] = {}

    def register(self, provider_id: str, provider: Provider, info: ProviderInfo) -> None:
        """Register a provider with its metadata."""
        self._providers[provider_id] = (provider, info)

    def get_provider(self, provider_id: str) -> Optional[Provider]:
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
