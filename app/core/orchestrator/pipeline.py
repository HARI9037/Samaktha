from __future__ import annotations

from pydantic import BaseModel

from app.core.contracts import (
    ExecutionPlan,
    PreparedContext,
    RoutingDecision,
    RuntimeResult,
    RuntimeTask,
)
from app.runtime.report import ExecutionReport


class PipelineState(BaseModel):
    """State captured while the orchestrator coordinates one request."""

    request: str
    context: PreparedContext | None = None
    execution_plan: ExecutionPlan | None = None
    runtime_task: RuntimeTask | None = None
    routing_decision: RoutingDecision | None = None
    runtime_result: RuntimeResult | None = None
    execution_report: ExecutionReport | None = None
