from typing import Optional

from app.models.models import ModelInfo
from app.models.registry import ModelRegistry


class ModelManager:
    """Coordinates access to the ModelRegistry."""

    def __init__(self, registry: ModelRegistry) -> None:
        self._registry = registry

    def register_model(self, model: ModelInfo) -> None:
        """Register or replace model metadata."""
        self._registry.register(model)

    def resolve_model(self, model_id: str) -> Optional[ModelInfo]:
        """Resolve model metadata from the registry."""
        return self._registry.get(model_id)

    def list_models(self) -> list[ModelInfo]:
        """List all registered models."""
        return self._registry.list_models()

    def list_models_by_provider(self, provider_id: str) -> list[ModelInfo]:
        """List all registered models for a provider."""
        return self._registry.list_by_provider(provider_id)
