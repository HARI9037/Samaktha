from pydantic import BaseModel, Field


class ProviderInfo(BaseModel):
    """Metadata describing an intelligence provider."""

    provider_id: str
    capabilities: list[str]
    models: list[str]
    supported_models: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class ProviderResponse(BaseModel):
    """Normalized response from an intelligence provider."""

    success: bool = True
    message: str | None = None
    content: str = ""
    provider_id: str = ""
    model_id: str = ""
    finish_reason: str | None = None
    usage: dict = Field(default_factory=dict)
    cost: dict = Field(default_factory=dict)
    latency_ms: float | None = None
    metadata: dict = Field(default_factory=dict)
