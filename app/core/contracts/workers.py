"""Phase 4.3 — Distributed Execution Contracts.

Defines the primitives for worker registration, assignment, and execution.
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.core.contracts.planning import TaskStatus
from app.core.contracts.runtime import RuntimeResult, RuntimeTask


class WorkerType(str, Enum):
    """The type of deployment mechanism for the worker."""
    LOCAL = "local"
    REMOTE = "remote"
    SERVERLESS = "serverless"


class WorkerCapability(BaseModel):
    """An action type a worker can handle."""
    action_type: str
    confidence: float = Field(ge=0.0, le=1.0)


class WorkerDefinition(BaseModel):
    """Describes a registered worker."""
    worker_id: str
    name: str
    type: WorkerType
    capabilities: list[WorkerCapability] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def supports_action(self, action_type: str) -> bool:
        return any(cap.action_type == action_type for cap in self.capabilities)

    def get_capability_confidence(self, action_type: str) -> float:
        for cap in self.capabilities:
            if cap.action_type == action_type:
                return cap.confidence
        return 0.0


class WorkerAssignment(BaseModel):
    """Ties a RuntimeTask to a specific worker."""
    assignment_id: str = Field(default_factory=lambda: f"assign-{uuid4()}")
    task_id: str
    worker_id: str
    action_type: str
    status: TaskStatus = TaskStatus.PENDING
    assigned_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkerResult(BaseModel):
    """Result returned by a worker after execution."""
    worker_id: str
    assignment_id: str
    runtime_result: RuntimeResult
    metadata: dict[str, Any] = Field(default_factory=dict)
