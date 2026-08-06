from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class WorkerLifecycleState(StrEnum):
    CREATED = "created"
    ASSIGNED = "assigned"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


@dataclass
class ExecutionWorker:
    worker_id: str
    task_id: str
    status: WorkerLifecycleState = WorkerLifecycleState.CREATED
    priority: int = 0
    required_capability: str = ""
    required_tools: tuple[str, ...] = ()
    required_provider: str | None = None
    dependencies: tuple[str, ...] = ()
    budget: dict[str, int] = field(default_factory=dict)
    timeout: float | None = None
    result: dict[str, Any] | None = None
    confidence: float = 0.0
    execution_time: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WorkerResult:
    worker_id: str
    success: bool
    output: dict[str, Any]
    confidence: float
    provenance: str
    execution_metrics: dict[str, Any]
    errors: tuple[str, ...] = ()

