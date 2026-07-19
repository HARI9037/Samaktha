from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RoutingDecision(BaseModel):
    """Router output describing model/provider selection without binding execution."""

    provider_id: str
    model_id: str
    reasoning_summary: str
    constraints: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
