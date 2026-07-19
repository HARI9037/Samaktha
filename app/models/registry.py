from typing import Dict, List, Optional

from app.models.models import ModelInfo


class ModelRegistry:
    """Stores model metadata separately from provider implementations."""

    def __init__(self) -> None:
        self._models: Dict[str, ModelInfo] = {}

    def register(self, model: ModelInfo) -> None:
        """Register or replace model metadata by model ID."""
        self._models[model.model_id] = model

    def get(self, model_id: str) -> Optional[ModelInfo]:
        """Retrieve model metadata by model ID."""
        return self._models.get(model_id)

    def list_models(self) -> List[ModelInfo]:
        """List all registered model metadata."""
        return list(self._models.values())

    def list_by_provider(self, provider_id: str) -> List[ModelInfo]:
        """List registered models owned by a provider."""
        return [
            model
            for model in self._models.values()
            if model.provider_id == provider_id
        ]
