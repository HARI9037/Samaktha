from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.contracts.state import ExecutionStatus


class WorkflowState(BaseModel):
    workflow_id: str
    status: ExecutionStatus = ExecutionStatus.CREATED
    current_step: int = 0
    total_steps: int = 0
    completed_steps: int = 0
    failed_step: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    results: list[Any] = Field(default_factory=list)
    completed_task_ids: set[str] = Field(default_factory=set)
    failed_task_ids: set[str] = Field(default_factory=set)
    errors: list[str] = Field(default_factory=list)
