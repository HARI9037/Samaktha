from __future__ import annotations

from uuid import uuid4

from app.core.gambit.goal_parser import GoalParser
from app.core.contracts.planning import (
    ExecutionPlan,
    GoalComplexity,
    RouterRequest,
    SkillRegistry,
)
from app.core.gambit.skill_registry import InMemorySkillRegistry
from app.core.gambit.task_decomposer import TaskDecomposer
from app.core.gambit.workflow_engine import WorkflowEngine


class Planner:
    """Coordinates goal parsing, skill discovery, and plan generation."""

    def __init__(
        self,
        goal_parser: GoalParser | None = None,
        task_decomposer: TaskDecomposer | None = None,
        workflow_engine: WorkflowEngine | None = None,
        skill_registry: SkillRegistry | None = None,
    ) -> None:
        self._goal_parser = goal_parser or GoalParser()
        self._task_decomposer = task_decomposer or TaskDecomposer()
        self._workflow_engine = workflow_engine or WorkflowEngine()
        self._skill_registry = skill_registry or InMemorySkillRegistry()

    async def plan(self, request: str) -> ExecutionPlan:
        goal = self._goal_parser.parse(request)
        skill_matches = await self._skill_registry.search(goal.raw_request)
        tasks = self._task_decomposer.decompose(goal, skill_matches)
        workflow = self._workflow_engine.build(tasks)

        return ExecutionPlan(
            plan_id=f"plan-{uuid4()}",
            goal=goal,
            tasks=tasks,
            workflow=workflow,
            router_request=self._router_request_for_goal(goal),
            skill_matches=skill_matches,
            notes=[
                "GAMBIT produced a plan only; Runtime must execute it.",
                "Every runtime action must pass through CAP before execution.",
                "Model selection must be requested through the Router.",
            ],
        )

    @staticmethod
    def _router_request_for_goal(goal) -> RouterRequest:
        return RouterRequest(
            purpose=goal.summary,
            complexity=goal.complexity,
            estimated_context_tokens=goal.estimated_context_tokens,
            requires_local_model=goal.requires_local_model,
            requires_code=goal.requires_code,
            requires_reasoning=goal.complexity == GoalComplexity.HIGH,
        )
