from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.contracts.planning import PlanTask


class ExecutionPause(BaseModel):
    """Represents a generalized pause condition during execution."""

    reason: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class PendingPause(BaseModel):
    """Context required to resume a specific task after a pause."""

    task_id: str
    pause: ExecutionPause
    paused_at: datetime = Field(default_factory=datetime.utcnow)
    resume_overrides: dict[str, Any] = Field(default_factory=dict)
