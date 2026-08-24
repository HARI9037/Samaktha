from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

class ExecutionStatus(str, Enum):
    CREATED = "created"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    RUNNING = "running"
    PAUSED = "paused"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


TERMINAL_EXECUTION_STATUSES = frozenset({
    ExecutionStatus.COMPLETED,
    ExecutionStatus.FAILED,
    ExecutionStatus.DENIED,
    ExecutionStatus.CANCELLED,
    ExecutionStatus.TIMED_OUT,
})


_PUBLIC_TRANSITIONS: dict[ExecutionStatus, frozenset[ExecutionStatus]] = {
    ExecutionStatus.CREATED: frozenset({
        ExecutionStatus.PLANNING,
        ExecutionStatus.RECOVERING,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.TIMED_OUT,
    }),
    ExecutionStatus.PLANNING: frozenset({
        ExecutionStatus.AWAITING_APPROVAL,
        ExecutionStatus.RUNNING,
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.DENIED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.TIMED_OUT,
        ExecutionStatus.RECOVERING,
    }),
    ExecutionStatus.AWAITING_APPROVAL: frozenset({
        ExecutionStatus.APPROVED,
        ExecutionStatus.DENIED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.TIMED_OUT,
        ExecutionStatus.RECOVERING,
    }),
    ExecutionStatus.APPROVED: frozenset({
        ExecutionStatus.RUNNING,
        ExecutionStatus.AWAITING_APPROVAL,
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.TIMED_OUT,
    }),
    ExecutionStatus.RUNNING: frozenset({
        ExecutionStatus.AWAITING_APPROVAL,
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.TIMED_OUT,
        ExecutionStatus.RECOVERING,
    }),
    ExecutionStatus.RECOVERING: frozenset({
        ExecutionStatus.PLANNING,
        ExecutionStatus.RUNNING,
        ExecutionStatus.AWAITING_APPROVAL,
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.TIMED_OUT,
    }),
}

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
    principal_id: str | None = None
    session_id: str | None = None
    request: str | None = None
    pending_approval_id: str | None = None
    pending_task_id: str | None = None
    result_available: bool = False
    error: str | None = None
    current_tasks: dict[str, TaskExecutionState] = Field(default_factory=dict)
    completed_tasks: set[str] = Field(default_factory=set)
    failed_tasks: set[str] = Field(default_factory=set)
    blocked_tasks: set[str] = Field(default_factory=set)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_EXECUTION_STATUSES

    def transition(self, status: ExecutionStatus, *, error: str | None = None) -> None:
        """Apply one validated public lifecycle transition in place."""
        if status == self.status:
            return
        if self.terminal:
            raise ValueError(
                f"Terminal execution cannot transition from {self.status.value} "
                f"to {status.value}."
            )
        allowed = _PUBLIC_TRANSITIONS.get(self.status, frozenset())
        if status not in allowed:
            raise ValueError(
                f"Invalid execution transition: {self.status.value} -> {status.value}."
            )
        now = datetime.now(timezone.utc)
        self.status = status
        self.updated_at = now
        if status in {ExecutionStatus.PLANNING, ExecutionStatus.RUNNING}:
            self.started_at = self.started_at or now
        if status in TERMINAL_EXECUTION_STATUSES:
            self.completed_at = now
        if error is not None:
            self.error = error
