from typing import List, Optional

from pydantic import BaseModel, Field


class ToolInfo(BaseModel):
    """Metadata describing a registered tool and its capabilities."""

    tool_id: str
    description: str
    capabilities: List[str] = Field(default_factory=list)
    version: str | None = None
    input_schema: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)


class DocumentResult(BaseModel):
    """Normalized document representation from Docling."""

    title: str | None = None
    page_count: int = 0
    sections: List[str] = Field(default_factory=list)
    tables: List[str] = Field(default_factory=list)
    images: List[str] = Field(default_factory=list)
    text: str = ""
    metadata: dict[str, object] = Field(default_factory=dict)
