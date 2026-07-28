"""Phase 6.1 — Samaktha Agent Configuration.

Configuration options for the Agent Runtime layer.
"""

from pydantic import BaseModel, Field

class AgentConfig(BaseModel):
    """Configuration options for the Samaktha Agent Runtime."""
    default_provider: str = Field(default="local")
    default_personality: str = Field(default="samaktha-core")
    streaming_enabled: bool = Field(default=True)
    memory_enabled: bool = Field(default=True)
    multimodal_enabled: bool = Field(default=True)
    tools_enabled: bool = Field(default=True)
    max_context_tokens: int = Field(default=16000)
    show_tool_output: bool = Field(default=False, description="When True, render raw tool outputs in the chat with a header separator.")
