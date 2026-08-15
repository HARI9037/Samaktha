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
    BLOCKED_BY_DEPENDENCY = "blocked_by_dependency"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


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


class GoalIntent(StrEnum):
    """Structured intent identified for a goal."""

    READ_RESOURCE = "read_resource"
    WRITE_RESOURCE = "write_resource"
    LIST_DIRECTORY = "list_directory"
    SEARCH_RESOURCE = "search_resource"
    DELETE_MEMORY = "delete_memory"
    DELETE_RESOURCE = "delete_resource"
    MOVE_RESOURCE = "move_resource"
    COPY_RESOURCE = "copy_resource"
    RENAME_RESOURCE = "rename_resource"
    SEARCH_MEMORY = "search_memory"
    GENERATE_CODE = "generate_code"
    ANSWER_QUESTION = "answer_question"
    OPERATE_WINDOWS = "operate_windows"
    RUN_COMMAND = "run_command"
    CLIPBOARD = "clipboard"
    SEND_NOTIFICATION = "send_notification"
    SEARCH_INTERNET = "search_internet"
    USE_BROWSER = "use_browser"
    SEND_EMAIL = "send_email"
    MANAGE_CALENDAR = "manage_calendar"
    PLAY_MEDIA = "play_media"
    READ_EMAIL = "read_email"
    REPLY_EMAIL = "reply_email"
    FORWARD_EMAIL = "forward_email"
    SEND_MESSAGE = "send_message"
    READ_MESSAGES = "read_messages"
    SEARCH_MESSAGES = "search_messages"
    SEARCH_CONTACT = "search_contact"


class Goal(BaseModel):
    """Normalized representation of a user goal."""

    goal_id: str
    raw_request: str
    summary: str
    complexity: GoalComplexity
    intent: GoalIntent = GoalIntent.ANSWER_QUESTION
    target_path: str | None = None
    query: str | None = None
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
    execution_action_type: str = "text_generation"
    origin: str = "planner"
    metadata: dict = Field(default_factory=dict)
    
    # Phase 4.3 - Distributed Execution Metadata
    worker_requirement: str | None = None
    preferred_worker: str | None = None


class WorkflowStep(BaseModel):
    """A runtime-facing workflow step composed of one or more tasks."""

    step_id: str
    stage: WorkflowStage
    title: str
    task_ids: list[str]
    metadata: dict = Field(default_factory=dict)


class ExecutionPlan(BaseModel):
    """Complete structured plan produced by a planning subsystem."""

    plan_id: str
    goal: Goal
    tasks: list[PlanTask]
    workflow: list[WorkflowStep]
    router_request: RouterRequest
    skill_matches: list[SkillMatch] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    used_skill_ids: list[str] = Field(default_factory=list)
    used_skill_names: list[str] = Field(default_factory=list)
    planner_reasoning: list[str] = Field(default_factory=list)


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


# ---------------------------------------------------------------------------
# Phase 3.1 – Reflection Engine contracts
# ---------------------------------------------------------------------------


class FailureCause(StrEnum):
    """Detected root cause category of a task failure."""

    PROVIDER_ERROR = "provider_error"
    TOOL_ERROR = "tool_error"
    POLICY_BLOCK = "policy_block"
    PARTIAL_OUTPUT = "partial_output"
    REPEATED_FAILURE = "repeated_failure"
    UNKNOWN = "unknown"


class ReplanRecommendation(StrEnum):
    """Deterministic replanning recommendation produced by reflection."""

    REPLAN_IMMEDIATELY = "replan_immediately"
    REPLAN_WITH_CONTEXT = "replan_with_context"
    RETRY_SAME_PLAN = "retry_same_plan"
    ABANDON = "abandon"


class ReflectionResult(BaseModel):
    """Rich reflection output produced by ReflectionEngine.reflect_on_report()."""

    plan_id: str
    reflection_id: str
    total_tasks: int = 0
    completed_count: int = 0
    failed_count: int = 0
    blocked_count: int = 0
    success_rate: float = 0.0
    failure_causes: list[FailureCause] = Field(default_factory=list)
    repeated_failures: list[str] = Field(default_factory=list)
    replan_recommendation: ReplanRecommendation = ReplanRecommendation.RETRY_SAME_PLAN
    replan_worthwhile: bool = False
    lessons: list[str] = Field(default_factory=list)
    follow_up_tasks: list[PlanTask] = Field(default_factory=list)
    duration_ms: int = 0


# ---------------------------------------------------------------------------
# Phase 5.7 – Planner-level result envelope
# ---------------------------------------------------------------------------


class PlannerStatus(StrEnum):
    """Outcome of a planning cycle returned to the Orchestrator."""

    OK = "ok"
    """Plan was produced successfully; Workflow should execute it."""

    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    """A required capability is not installed.

    Workflow must NOT execute.  The Orchestrator must return a user-facing
    message via CAPABILITY_UNAVAILABLE_MESSAGE without invoking the Provider.
    """


class PlannerResult(BaseModel):
    """Envelope returned by Planner.plan_with_capability_check().

    The Orchestrator inspects .status before deciding whether to hand
    .plan to the Workflow Engine.
    """

    status: PlannerStatus = PlannerStatus.OK
    plan: ExecutionPlan | None = None
    required_capability: str | None = None
    """Human-readable capability name when status == CAPABILITY_UNAVAILABLE."""

