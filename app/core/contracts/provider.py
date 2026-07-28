from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ProviderCapability(str, Enum):
    TEXT_GENERATION = "text_generation"
    EMBEDDING = "embedding"
    VISION = "vision"
    AUDIO = "audio"
    CODE = "code"


class ProviderDefinition(BaseModel):
    provider_id: str
    name: str
    capabilities: list[ProviderCapability] = Field(default_factory=list)
    context_limit: int = 0
    cost_profile: str = "unknown"
    latency_profile: str = "unknown"


class ProviderRequest(BaseModel):
    task: str
    capability_required: ProviderCapability
    constraints: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderResponse(BaseModel):
    content: str
    usage: dict[str, int] = Field(default_factory=dict)
    latency: float = 0.0
    provider_id: str
