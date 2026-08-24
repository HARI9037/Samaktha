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
from app.personality.models import PersonalityEvaluation, PromptComposition
from app.personality.reflection_models import ReflectionReport


from app.workflow.state import WorkflowState

class PipelineState(BaseModel):
    """State captured while the orchestrator coordinates one request."""

    request: str
    context: PreparedContext | None = None
    personality_evaluation: PersonalityEvaluation | None = None
    prompt_composition: PromptComposition | None = None
    reflection_report: ReflectionReport | None = None
    execution_plan: ExecutionPlan | None = None
    runtime_task: RuntimeTask | None = None
    routing_decision: RoutingDecision | None = None
    runtime_result: RuntimeResult | None = None
    execution_report: ExecutionReport | None = None
    workflow_state: WorkflowState | None = None

from typing import Any
from app.core.contracts.pause import ExecutionPause

class PipelineEvent(BaseModel):
    """Event emitted by the orchestrator (e.g. for a requested pause)."""
    type: str
    pause: ExecutionPause | None = None
    task_id: str | None = None
    data: dict[str, Any] = {}
