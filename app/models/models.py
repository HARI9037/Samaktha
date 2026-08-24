from pydantic import BaseModel, Field

from app.core.contracts.policy import ExecutionLocation


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
    execution_location: ExecutionLocation = ExecutionLocation.CLOUD
    maximum_output: int = 4096
    supports_vision: bool = False
    supports_reasoning: bool = False
    version: str | None = None
    input_cost_per_1k: float = 0.0
    output_cost_per_1k: float = 0.0
    capability_source: str = "registered"
    metadata: dict = Field(default_factory=dict)
