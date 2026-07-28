"""Phase 4.2 — Agent contract models.

Agents are planning abstractions only.
They decompose goals into PlanTasks; Runtime never sees AgentDefinition.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field

from app.core.contracts.planning import Goal, PlanTask, TaskKind, TaskStatus


# ---------------------------------------------------------------------------
# Agent role taxonomy
# ---------------------------------------------------------------------------


class AgentRole(StrEnum):
    """Specialised roles available in the multi-agent orchestration layer."""

    PLANNER = "planner"
    RESEARCHER = "researcher"
    ANALYST = "analyst"
    EXECUTOR = "executor"
    REVIEWER = "reviewer"
    VERIFIER = "verifier"


# ---------------------------------------------------------------------------
# Capability descriptor
# ---------------------------------------------------------------------------


class AgentCapability(BaseModel):
    """Describes a single capability an agent can perform."""

    capability_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str
    supported_task_types: list[TaskKind] = Field(default_factory=list)
    # 0.0–1.0 confidence the agent can handle this capability reliably
    confidence: float = 1.0


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------


class AgentDefinition(BaseModel):
    """Describes a registered specialised agent."""

    agent_id: str
    name: str
    role: AgentRole
    capabilities: list[AgentCapability] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    @property
    def total_confidence(self) -> float:
        """Sum of all capability confidence scores — used for registry ranking."""
        if not self.capabilities:
            return 0.0
        return sum(c.confidence for c in self.capabilities)

    def supports_task_type(self, task_type: TaskKind) -> bool:
        """Return True if any capability covers *task_type*."""
        return any(task_type in cap.supported_task_types for cap in self.capabilities)


# ---------------------------------------------------------------------------
# Agent task (intermediate planning artifact)
# ---------------------------------------------------------------------------


class AgentTask(BaseModel):
    """A unit of work delegated to a specific agent during multi-agent planning.

    AgentTask objects are created by AgentPlanner and immediately converted to
    PlanTask objects before the workflow layer ever sees them.
    """

    task_id: str = Field(default_factory=lambda: f"agent-task-{uuid4()}")
    agent_id: str
    objective: str
    kind: TaskKind = TaskKind.EXECUTE_VIA_RUNTIME
    dependencies: list[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 0
    metadata: dict = Field(default_factory=dict)

    def to_plan_task(self) -> PlanTask:
        """Convert this AgentTask to a PlanTask suitable for WorkflowEngine."""
        return PlanTask(
            task_id=self.task_id,
            title=self.objective[:120],
            kind=self.kind,
            description=self.objective,
            dependencies=self.dependencies,
            status=self.status,
            origin="agent_planner",
            metadata={
                "agent_id": self.agent_id,
                "agent_priority": self.priority,
                **self.metadata,
            },
        )


# ---------------------------------------------------------------------------
# Agent plan (intermediate multi-agent decomposition)
# ---------------------------------------------------------------------------


class AgentPlan(BaseModel):
    """Multi-agent execution plan produced by AgentPlanner.

    This is an intermediate artifact.  AgentPlanner converts it to an
    ExecutionPlan before handing it to the WorkflowEngine.
    """

    plan_id: str = Field(default_factory=lambda: f"agent-plan-{uuid4()}")
    goal: Goal
    assigned_agents: list[AgentDefinition] = Field(default_factory=list)
    agent_tasks: list[AgentTask] = Field(default_factory=list)
    reasoning: list[str] = Field(default_factory=list)
