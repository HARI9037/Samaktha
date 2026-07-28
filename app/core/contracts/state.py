from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

class ExecutionStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"

class TaskExecutionState(BaseModel):
    task_id: str
    status: ExecutionStatus = ExecutionStatus.CREATED
    attempt_number: int = 1
    assigned_worker: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class ExecutionState(BaseModel):
    execution_id: str
    status: ExecutionStatus = ExecutionStatus.CREATED
    current_tasks: dict[str, TaskExecutionState] = Field(default_factory=dict)
    completed_tasks: set[str] = Field(default_factory=set)
    failed_tasks: set[str] = Field(default_factory=set)
    blocked_tasks: set[str] = Field(default_factory=set)
    started_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
