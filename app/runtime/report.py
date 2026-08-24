from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.core.contracts.trace import ExecutionTrace


class ExecutionTruthState(StrEnum):
    NOT_STARTED = "not_started"
    PLANNED = "planned"
    WAITING_APPROVAL = "waiting_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class ExecutionReport(BaseModel):
    """Generic runtime execution summary."""

    plan_id: str
    success: bool
    execution_state: ExecutionTruthState = ExecutionTruthState.NOT_STARTED
    executed_tasks: list[str] = Field(default_factory=list)
    skipped_tasks: list[str] = Field(default_factory=list)
    tool_results: list[Any] = Field(default_factory=list)
    provider_results: list[Any] = Field(default_factory=list)
    approval_status: str = "unknown"
    worker_information: list[dict[str, Any]] = Field(default_factory=list)
    retry_count: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    blocked_tasks: int = 0
    results: list[Any] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    trace: ExecutionTrace | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
