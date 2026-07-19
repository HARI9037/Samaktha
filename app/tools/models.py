from typing import List

from pydantic import BaseModel, Field


class ToolInfo(BaseModel):
    """Metadata describing a registered tool and its capabilities."""

    tool_id: str
    description: str
    capabilities: List[str] = Field(default_factory=list)
