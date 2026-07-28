"""Phase 4.2.3 — Agent Planner.

Responsibility: convert complex goals into multi-agent ExecutionPlans.

Constraints (enforced by architecture):
  - Must NOT call providers, tools, or Runtime.
  - Must NOT import app.runtime, app.providers, app.tools, or app.workflow.
  - Pure planning: produces data structures, never executes anything.
"""

from __future__ import annotations

from uuid import uuid4

from app.core.contracts.agents import (
    AgentCapability,
    AgentDefinition,
    AgentPlan,
    AgentRole,
    AgentTask,
)
from app.core.contracts.planning import (
    ExecutionPlan,
    Goal,
    GoalComplexity,
    PlanTask,
    RouterRequest,
    TaskKind,
    TaskStatus,
    WorkflowStep,
    WorkflowStage,
)
from app.core.gambit.agents import AgentRegistry
from app.core.gambit.goal_parser import GoalParser


# ---------------------------------------------------------------------------
# Default agent pool (used when no custom registry is supplied)
# ---------------------------------------------------------------------------

def _build_default_registry() -> AgentRegistry:
    """Build a default AgentRegistry with one agent per role covering all task kinds."""
    registry = AgentRegistry()

    role_task_map: list[tuple[AgentRole, str, str, list[TaskKind], float]] = [
        (
            AgentRole.PLANNER,
            "agent-planner-default",
            "Planning Agent",
            [TaskKind.PLAN, TaskKind.UNDERSTAND],
            0.95,
        ),
        (
            AgentRole.RESEARCHER,
            "agent-researcher-default",
            "Research Agent",
            [TaskKind.RETRIEVE_CONTEXT, TaskKind.UNDERSTAND],
            0.90,
        ),
        (
            AgentRole.ANALYST,
            "agent-analyst-default",
            "Analysis Agent",
            [TaskKind.UNDERSTAND, TaskKind.TRANSFORM, TaskKind.PLAN],
            0.88,
        ),
        (
            AgentRole.EXECUTOR,
            "agent-executor-default",
            "Execution Agent",
            [TaskKind.EXECUTE_VIA_RUNTIME, TaskKind.TRANSFORM],
            0.92,
        ),
        (
            AgentRole.REVIEWER,
            "agent-reviewer-default",
            "Review Agent",
            [TaskKind.VERIFY, TaskKind.REFLECT],
            0.87,
        ),
        (
            AgentRole.VERIFIER,
            "agent-verifier-default",
            "Verification Agent",
            [TaskKind.VERIFY],
            0.85,
        ),
    ]

    for role, agent_id, name, task_kinds, confidence in role_task_map:
        capability = AgentCapability(
            name=f"{name} Core Capability",
            description=f"Core task handling for {name}.",
            supported_task_types=task_kinds,
            confidence=confidence,
        )
        registry.register(
            AgentDefinition(
                agent_id=agent_id,
                name=name,
                role=role,
                capabilities=[capability],
            )
        )

    return registry


# ---------------------------------------------------------------------------
# Decomposition rules: TaskKind → preferred AgentRole
# ---------------------------------------------------------------------------

_TASK_KIND_TO_ROLE: dict[TaskKind, AgentRole] = {
    TaskKind.UNDERSTAND: AgentRole.ANALYST,
    TaskKind.RETRIEVE_CONTEXT: AgentRole.RESEARCHER,
    TaskKind.PLAN: AgentRole.PLANNER,
    TaskKind.TRANSFORM: AgentRole.EXECUTOR,
    TaskKind.EXECUTE_VIA_RUNTIME: AgentRole.EXECUTOR,
    TaskKind.VERIFY: AgentRole.VERIFIER,
    TaskKind.REFLECT: AgentRole.REVIEWER,
}


# ---------------------------------------------------------------------------
# AgentPlanner
# ---------------------------------------------------------------------------


class AgentPlanner:
    """Converts complex user goals into multi-agent ExecutionPlans.

    Pipeline:
      1. GoalParser  → Goal
      2. _decompose  → list[AgentTask]  (rule-based, deterministic)
      3. AgentRegistry.find_best_agent  → assign AgentDefinition per task
      4. AgentTask.to_plan_task()  → PlanTask  (agent_id in metadata)
      5. Build ExecutionPlan with WorkflowStep scaffold
    """

    def __init__(self, registry: AgentRegistry | None = None) -> None:
        self._registry = registry or _build_default_registry()
        self._goal_parser = GoalParser()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_agent_plan(self, request: str) -> AgentPlan:
        """Return the intermediate multi-agent plan for *request*.

        Use this when you need to inspect agent assignments before converting
        to an ExecutionPlan.
        """
        goal = self._goal_parser.parse(request)
        agent_tasks, assigned_agents, reasoning = self._decompose(goal)

        return AgentPlan(
            plan_id=f"agent-plan-{uuid4()}",
            goal=goal,
            assigned_agents=list(assigned_agents.values()),
            agent_tasks=agent_tasks,
            reasoning=reasoning,
        )

    def plan_with_agents(self, request: str) -> ExecutionPlan:
        """Parse *request* and produce an ExecutionPlan ready for WorkflowEngine."""
        agent_plan = self.create_agent_plan(request)
        return self._to_execution_plan(agent_plan)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _decompose(
        self, goal: Goal
    ) -> tuple[list[AgentTask], dict[str, AgentDefinition], list[str]]:
        """Decompose *goal* into a list of AgentTasks with proper dependencies."""
        reasoning: list[str] = []
        assigned_agents: dict[str, AgentDefinition] = {}  # agent_id → definition
        agent_tasks: list[AgentTask] = []

        # Determine task kinds required by complexity
        task_kinds = self._task_kinds_for_goal(goal)

        prev_task_id: str | None = None
        for priority, kind in enumerate(task_kinds):
            preferred_role = _TASK_KIND_TO_ROLE.get(kind, AgentRole.EXECUTOR)
            agent = (
                self._registry.find_best_agent(kind)
                or self._registry.find_agent_for_role(preferred_role)
            )

            if agent is None:
                # Fallback: create a minimal executor definition
                agent = AgentDefinition(
                    agent_id=f"fallback-{kind.value}",
                    name=f"Fallback {kind.value} Agent",
                    role=preferred_role,
                )
                reasoning.append(f"No registered agent for {kind.value}; using fallback.")
            else:
                reasoning.append(
                    f"Assigned '{agent.name}' (role={agent.role.value}) "
                    f"to task kind '{kind.value}'."
                )

            assigned_agents[agent.agent_id] = agent

            task = AgentTask(
                agent_id=agent.agent_id,
                objective=self._objective_for(goal, kind),
                kind=kind,
                dependencies=[prev_task_id] if prev_task_id else [],
                priority=priority,
                metadata={"goal_id": goal.goal_id, "agent_role": agent.role.value},
            )
            agent_tasks.append(task)
            prev_task_id = task.task_id

        return agent_tasks, assigned_agents, reasoning

    @staticmethod
    def _task_kinds_for_goal(goal: Goal) -> list[TaskKind]:
        """Return an ordered list of TaskKinds required for *goal* complexity."""
        kinds: list[TaskKind] = [TaskKind.UNDERSTAND]

        if goal.requires_long_context:
            kinds.append(TaskKind.RETRIEVE_CONTEXT)

        kinds.append(TaskKind.PLAN)
        kinds.append(TaskKind.EXECUTE_VIA_RUNTIME)

        if goal.complexity in {GoalComplexity.MEDIUM, GoalComplexity.HIGH}:
            kinds.append(TaskKind.VERIFY)

        kinds.append(TaskKind.REFLECT)
        return kinds

    @staticmethod
    def _objective_for(goal: Goal, kind: TaskKind) -> str:
        labels = {
            TaskKind.UNDERSTAND: "Understand the goal and extract constraints",
            TaskKind.RETRIEVE_CONTEXT: "Retrieve relevant context and supporting information",
            TaskKind.PLAN: "Produce a safe, CAP-governed execution strategy",
            TaskKind.TRANSFORM: "Transform data or artifacts as required",
            TaskKind.EXECUTE_VIA_RUNTIME: "Execute the planned actions via Runtime",
            TaskKind.VERIFY: "Verify plan completeness and output correctness",
            TaskKind.REFLECT: "Reflect on execution and record lessons learned",
        }
        return f"{labels.get(kind, kind.value)}: {goal.summary[:120]}"

    def _to_execution_plan(self, agent_plan: AgentPlan) -> ExecutionPlan:
        """Convert an AgentPlan into a standard ExecutionPlan."""
        plan_tasks: list[PlanTask] = [
            at.to_plan_task() for at in agent_plan.agent_tasks
        ]

        # Build a minimal workflow scaffold (one step per task)
        workflow_steps: list[WorkflowStep] = [
            WorkflowStep(
                step_id=f"step-{pt.task_id}",
                stage=WorkflowStage.ACT,
                title=pt.title,
                task_ids=[pt.task_id],
            )
            for pt in plan_tasks
        ]

        goal = agent_plan.goal
        router_request = RouterRequest(
            purpose=goal.summary,
            complexity=goal.complexity,
            estimated_context_tokens=goal.estimated_context_tokens,
            requires_local_model=goal.requires_local_model,
            requires_code=goal.requires_code,
            requires_reasoning=goal.complexity == GoalComplexity.HIGH,
        )

        return ExecutionPlan(
            plan_id=f"plan-{uuid4()}",
            goal=goal,
            tasks=plan_tasks,
            workflow=workflow_steps,
            router_request=router_request,
            notes=[
                "Plan produced by AgentPlanner (Phase 4.2).",
                "Each task carries agent_id in metadata for observability.",
                "Runtime executes PlanTasks; it is unaware of agent abstractions.",
            ],
            planner_reasoning=agent_plan.reasoning,
        )
