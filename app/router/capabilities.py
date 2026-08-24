from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.core.contracts.policy import ExecutionLocation


class ProviderCapability(BaseModel):
    """Router-local model describing the performance characteristics of a provider."""

    provider_id: str
    model_id: str
    capabilities: List[str] = Field(default_factory=list)
    execution_location: ExecutionLocation = ExecutionLocation.CLOUD

    # Scores are 1–10; higher is better in each dimension.
    reasoning_score: int = 5
    coding_score: int = 5
    speed_score: int = 5
    privacy_score: int = 5   # high = supports private / local execution
    cost_score: int = 5      # high = lower cost
    context_window: int = 0
    maximum_output: int = 0
    input_cost_per_1k: float = 0.0
    output_cost_per_1k: float = 0.0
    latency_ms: float | None = None
    version: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class CapabilityRegistry:
    """In-memory store of provider capability metadata used by the Router."""

    def __init__(self) -> None:
        self._capabilities: Dict[tuple[str, str], ProviderCapability] = {}

    def register(self, capability: ProviderCapability) -> None:
        """Register capability metadata for a provider."""
        self._capabilities[(capability.provider_id, capability.model_id)] = capability

    def get(
        self,
        provider_id: str,
        model_id: str | None = None,
    ) -> Optional[ProviderCapability]:
        """Retrieve capability metadata for a specific provider."""
        if model_id is not None:
            return self._capabilities.get((provider_id, model_id))
        return next(
            (
                capability
                for (candidate_provider, _), capability in self._capabilities.items()
                if candidate_provider == provider_id
            ),
            None,
        )

    def all(self) -> List[ProviderCapability]:
        """Return all registered capabilities."""
        return list(self._capabilities.values())
