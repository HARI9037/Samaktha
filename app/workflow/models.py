from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.core.contracts import RuntimeTask
from app.runtime.report import ExecutionReport
from app.workflow.state import WorkflowState


class WorkflowTask(BaseModel):
    task_id: str
    name: str
    description: str
    runtime_task: RuntimeTask
    # Optional: populated when the task originated from AgentPlanner (Phase 4.2)
    agent_id: str | None = None
    # Phase 4.3 - Distributed Execution Metadata
    worker_requirement: str | None = None
    preferred_worker: str | None = None


class WorkflowResult(BaseModel):
    success: bool
    workflow_state: WorkflowState
    outputs: list[Any] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    execution_report: ExecutionReport | None = None
