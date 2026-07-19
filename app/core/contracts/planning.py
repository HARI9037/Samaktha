from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field


class GoalComplexity(StrEnum):
    """Estimated complexity for a user goal."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskStatus(StrEnum):
    """Lifecycle status for planned or runtime-reported tasks."""

    PENDING = "pending"
    READY = "ready"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskKind(StrEnum):
    """Semantic kind of task produced by planning."""

    UNDERSTAND = "understand"
    RETRIEVE_CONTEXT = "retrieve_context"
    PLAN = "plan"
    TRANSFORM = "transform"
    VERIFY = "verify"
    REFLECT = "reflect"
    EXECUTE_VIA_RUNTIME = "execute_via_runtime"


class WorkflowStage(StrEnum):
    """High-level workflow stages emitted for the runtime."""

    ANALYZE = "analyze"
    PREPARE = "prepare"
    ACT = "act"
    VERIFY = "verify"
    REFLECT = "reflect"


class Goal(BaseModel):
    """Normalized representation of a user goal."""

    goal_id: str
    raw_request: str
    summary: str
    complexity: GoalComplexity
    requires_long_context: bool = False
    requires_code: bool = False
    requires_local_model: bool = False
    requires_fast_response: bool = False
    estimated_context_tokens: int = 2000
    constraints: list[str] = Field(default_factory=list)


class Skill(BaseModel):
    """Reusable skill or workflow capability known to a planning subsystem."""

    skill_id: str
    name: str
    description: str
    triggers: list[str] = Field(default_factory=list)
    task_kinds: list[TaskKind] = Field(default_factory=list)


class SkillMatch(BaseModel):
    """A ranked skill match for a goal or task."""

    skill: Skill
    score: int
    reasons: list[str] = Field(default_factory=list)


class RouterRequest(BaseModel):
    """Model selection request that must be sent through the Router."""

    purpose: str
    complexity: GoalComplexity
    estimated_context_tokens: int
    requires_local_model: bool
    requires_code: bool
    requires_reasoning: bool
    requires_fast_response: bool = False
    max_latency_ms: float | None = None
    max_cost_per_1k_tokens: float | None = None


class PlanTask(BaseModel):
    """A structured task for Runtime execution."""

    task_id: str
    title: str
    kind: TaskKind
    description: str
    dependencies: list[str] = Field(default_factory=list)
    suggested_skills: list[str] = Field(default_factory=list)
    router_request: RouterRequest | None = None
    cap_required: bool = True
    status: TaskStatus = TaskStatus.PENDING


class WorkflowStep(BaseModel):
    """A runtime-facing workflow step composed of one or more tasks."""

    step_id: str
    stage: WorkflowStage
    title: str
    task_ids: list[str]


class ExecutionPlan(BaseModel):
    """Complete structured plan produced by a planning subsystem."""

    plan_id: str
    goal: Goal
    tasks: list[PlanTask]
    workflow: list[WorkflowStep]
    router_request: RouterRequest
    skill_matches: list[SkillMatch] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class TaskOutcome(BaseModel):
    """Runtime-reported outcome used by reflection."""

    task_id: str
    status: TaskStatus
    summary: str
    error: str | None = None


class PlanReflection(BaseModel):
    """Reflection over a completed or partially completed plan."""

    plan_id: str
    completed_task_ids: list[str] = Field(default_factory=list)
    failed_task_ids: list[str] = Field(default_factory=list)
    blocked_task_ids: list[str] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list)
    follow_up_tasks: list[PlanTask] = Field(default_factory=list)


class SkillRegistry(Protocol):
    """Protocol for skill discovery without binding planners to storage."""

    async def search(self, query: str, limit: int = 5) -> list[SkillMatch]:
        raise NotImplementedError
