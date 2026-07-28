from __future__ import annotations

from uuid import uuid4

import logging

from app.core.gambit.goal_parser import GoalParser

log = logging.getLogger(__name__)
from app.core.contracts.learning import SkillConfidence
from app.core.contracts.planning import (
    ExecutionPlan,
    GoalComplexity,
    RouterRequest,
    SkillRegistry,
    PlanTask,
    PlannerResult,
    PlannerStatus,
    TaskKind,
)
from app.core.gambit.skill_registry import InMemorySkillRegistry
from app.core.gambit.task_decomposer import TaskDecomposer
from app.core.gambit.plan_builder import PlanBuilder
from app.tools.capability_registry import CapabilityRegistry


class Planner:
    """Coordinates goal parsing, skill discovery, and plan generation."""

    def __init__(
        self,
        goal_parser: GoalParser | None = None,
        task_decomposer: TaskDecomposer | None = None,
        plan_builder: PlanBuilder | None = None,
        skill_registry: SkillRegistry | None = None,
        capability_registry: CapabilityRegistry | None = None,
        memory_manager: object | None = None,
    ) -> None:
        self._goal_parser = goal_parser or GoalParser()
        self._task_decomposer = task_decomposer or TaskDecomposer()
        self._plan_builder = plan_builder or PlanBuilder()
        self._skill_registry = skill_registry or InMemorySkillRegistry()
        self._capability_registry = capability_registry or CapabilityRegistry.default()
        self._memory_manager = memory_manager

    async def plan(self, request: str) -> ExecutionPlan:
        """Build an ExecutionPlan directly (no capability check).

        Prefer plan_with_capability_check() for the production path so that
        unknown capabilities stop before the Workflow Engine.
        """
        goal = self._goal_parser.parse(request)
        skill_matches = await self._skill_registry.search(goal.raw_request)
        tasks = self._task_decomposer.decompose(goal, skill_matches)
        
        used_skill_ids = []
        used_skill_names = []
        planner_reasoning = []

        if self._memory_manager:
            try:
                relevant = self._memory_manager.find_relevant_skills(request)
                limit = 3
                for result in relevant[:limit]:
                    skill = result.skill
                    if skill.confidence == SkillConfidence.LOW or not skill.is_active:
                        continue
                    skill_task = PlanTask(
                        task_id=f"skill-{skill.skill_id}",
                        title=skill.name,
                        kind=TaskKind.RETRIEVE_CONTEXT,
                        description=f"Execute learned skill: {skill.description}",
                        origin="skill_memory",
                    )
                    tasks.insert(0, skill_task)
                    used_skill_ids.append(skill.skill_id)
                    used_skill_names.append(skill.name)
                planner_reasoning.append(f"Injected {len(used_skill_ids)} relevant skills from memory.")
            except Exception:
                planner_reasoning.append("Memory manager available but skill injection failed.")
        else:
            planner_reasoning = ["No memory manager provided"]

        workflow = self._plan_builder.build(tasks)

        return ExecutionPlan(
            plan_id=f"plan-{uuid4()}",
            goal=goal,
            tasks=tasks,
            workflow=workflow,
            router_request=self._router_request_for_goal(goal),
            skill_matches=skill_matches,
            notes=[
                "GAMBIT produced a plan only; runtime must execute it.",
                "Every runtime action must pass through CAP before execution.",
                "Model selection must be requested through the Router.",
            ],
            used_skill_ids=used_skill_ids,
            used_skill_names=used_skill_names,
            planner_reasoning=planner_reasoning,
        )

    async def plan_with_capability_check(self, request: str) -> PlannerResult:
        """Build a plan with a Capability Registry gate.

        Flow:
          1. GoalParser → Goal + GoalIntent
          2. GoalParser.capability_domain_for_intent() → required domain
          3. CapabilityRegistry.is_installed(domain) ?
             YES → build ExecutionPlan → PlannerResult(OK, plan=...)
             NO  → PlannerResult(CAPABILITY_UNAVAILABLE, required_capability=domain)

        The Orchestrator MUST NOT call the Workflow Engine when
        PlannerResult.status == CAPABILITY_UNAVAILABLE.
        """
        goal = self._goal_parser.parse(request)
        required_domain = GoalParser.capability_domain_for_intent(goal.intent)

        # Only check the registry when a specific tool is required.
        if required_domain is not None and not self._capability_registry.is_installed(required_domain):
            return PlannerResult(
                status=PlannerStatus.CAPABILITY_UNAVAILABLE,
                required_capability=required_domain,
            )

        # Capability is available (or not required) — build the full plan.
        skill_matches = await self._skill_registry.search(goal.raw_request)
        tasks = self._task_decomposer.decompose(goal, skill_matches)
        workflow = self._plan_builder.build(tasks)

        plan = ExecutionPlan(
            plan_id=f"plan-{uuid4()}",
            goal=goal,
            tasks=tasks,
            workflow=workflow,
            router_request=self._router_request_for_goal(goal),
            skill_matches=skill_matches,
            notes=[
                "GAMBIT produced a plan only; runtime must execute it.",
                "Every runtime action must pass through CAP before execution.",
                "Model selection must be requested through the Router.",
            ],
            used_skill_ids=[],
            used_skill_names=[],
            planner_reasoning=["Capability registry check passed."],
        )
        log.debug("Planner generated ExecutionPlan with %d tasks.", len(tasks))
        return PlannerResult(status=PlannerStatus.OK, plan=plan)

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
