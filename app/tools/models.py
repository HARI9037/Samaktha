from enum import StrEnum
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from app.tools.framework.models import ToolPolicy


class CapabilityAvailability(StrEnum):
    """Truthful product availability derived from production tool wiring."""

    PRODUCTION_READY = "production_ready"
    LOCAL_ONLY = "local_only"
    SIMULATED = "simulated"
    UNAVAILABLE = "unavailable"
    INTERNAL_ONLY = "internal_only"


class ToolInfo(BaseModel):
    """Metadata describing a registered tool and its capabilities."""

    tool_id: str
    description: str
    capabilities: List[str] = Field(default_factory=list)
    version: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    category: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)
    approval_required: bool = False
    supported_actions: List[str] = Field(default_factory=list)
    available: bool = True
    policy: Optional[ToolPolicy] = None
    product_domain: str | None = None
    execution_mode: CapabilityAvailability = CapabilityAvailability.INTERNAL_ONLY
    side_effect_actions: List[str] = Field(default_factory=list)
    evidence_requirements: dict[str, str] = Field(default_factory=dict)
    natural_language_intents: List[str] = Field(default_factory=list)
    advertised: bool = False


class DocumentResult(BaseModel):
    """Normalized document representation from Docling."""

    title: str | None = None
    page_count: int = 0
    sections: List[str] = Field(default_factory=list)
    tables: List[str] = Field(default_factory=list)
    images: List[str] = Field(default_factory=list)
    text: str = ""
    metadata: dict[str, object] = Field(default_factory=dict)
