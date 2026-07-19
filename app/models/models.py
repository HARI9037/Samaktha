from pydantic import BaseModel, Field


class ModelInfo(BaseModel):
    """Metadata describing an AI model independently from its provider."""

    model_id: str
    provider_id: str
    display_name: str
    context_window: int
    supports_tools: bool
    supports_streaming: bool
    supports_images: bool
    supports_audio: bool
    reasoning_score: int
    coding_score: int
    speed_score: int
    cost_score: int
    privacy_score: int
    maximum_output: int = 4096
    supports_vision: bool = False
    supports_reasoning: bool = False
    metadata: dict = Field(default_factory=dict)
