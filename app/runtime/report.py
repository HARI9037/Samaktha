from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.runtime.trace import ExecutionTrace


class ExecutionReport(BaseModel):
    """Generic runtime execution summary."""

    plan_id: str
    success: bool
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    results: list[Any] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    trace: ExecutionTrace | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
