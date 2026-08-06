from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.contracts.planning import TaskStatus
from app.core.contracts.routing import RoutingDecision
from app.core.contracts.trace import ExecutionTrace
from app.core.contracts.policy import ExecutionPermit
from app.core.contracts.pause import ExecutionPause


class RuntimeContext(BaseModel):
    """Execution coordination context shared with Runtime implementations."""

    request_id: str = Field(description="Unique request identifier.")
    user_id: str | None = None
    session_id: str | None = None
    trace: ExecutionTrace | None = None
    event_bus: Any | None = Field(default=None, description="Injected RuntimeEventBus for publishing events.")
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeTask(BaseModel):
    """A typed runtime task accepted by Runtime implementations."""

    task_id: str
    title: str
    description: str
    action_type: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    
    # Phase 4.3 - Distributed Execution Metadata
    worker_requirement: str | None = None
    preferred_worker: str | None = None


class RuntimeResult(BaseModel):
    """Runtime execution result returned across subsystem boundaries."""

    task_id: str
    status: TaskStatus
    routing: RoutingDecision | None = None
    pause: ExecutionPause | None = None
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovedRuntimeTask(RuntimeTask):
    """A runtime task that has passed CAP governance and holds an ExecutionPermit.

    The Runtime will REFUSE to execute any task with permit=None.
    The Orchestrator is responsible for issuing permits before Workflow begins.
    """

    permit: ExecutionPermit | None = None
