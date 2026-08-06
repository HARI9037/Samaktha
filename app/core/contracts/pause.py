from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class ExecutionPause(BaseModel):
    """Represents a generalized pause condition during execution."""

    reason: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class PendingPause(BaseModel):
    """Context required to resume a specific task after a pause."""

    task_id: str
    pause: ExecutionPause
    paused_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resume_overrides: dict[str, Any] = Field(default_factory=dict)
