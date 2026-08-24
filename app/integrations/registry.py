"""P10.2 — Canonical Integration Registry."""

import logging
from typing import Dict, List, Optional

from app.integrations.contracts import IntegrationProvider

logger = logging.getLogger(__name__)


class IntegrationRegistry:
    """Central registry for all real external providers."""

    def __init__(self) -> None:
        self._providers: Dict[str, IntegrationProvider] = {}

    def register(self, provider_id: str, provider: IntegrationProvider) -> None:
        """Register a provider implementation."""
        if provider_id in self._providers:
            raise ValueError(f"Provider already registered: {provider_id}")
        self._providers[provider_id] = provider

    def unregister(self, provider_id: str) -> bool:
        """Remove a provider."""
        return self._providers.pop(provider_id, None) is not None

    def get(self, provider_id: str) -> Optional[IntegrationProvider]:
        """Retrieve a provider by its ID."""
        return self._providers.get(provider_id)

    def list_providers(self) -> List[str]:
        """List all registered provider IDs."""
        return list(self._providers.keys())
