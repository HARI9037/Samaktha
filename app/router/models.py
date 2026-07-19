from __future__ import annotations

from pydantic import BaseModel, Field


class ProviderModelRegistration(BaseModel):
    """Router-local metadata for an available provider model."""

    provider_id: str
    model_id: str
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
