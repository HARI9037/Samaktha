from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.core.contracts.planning import TaskStatus
from app.core.contracts.routing import RoutingDecision


class RuntimeContext(BaseModel):
    """Execution coordination context shared with Runtime implementations."""

    request_id: str = Field(description="Unique request identifier.")
    user_id: str | None = None
    session_id: str | None = None
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


class RuntimeResult(BaseModel):
    """Runtime execution result returned across subsystem boundaries."""

    task_id: str
    status: TaskStatus
    routing: RoutingDecision | None = None
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
