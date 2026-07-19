from __future__ import annotations

from uuid import uuid4
from typing import TYPE_CHECKING

from app.core.gambit.goal_parser import GoalParser
from app.core.contracts.planning import (
    ExecutionPlan,
    GoalComplexity,
    RouterRequest,
    SkillRegistry,
    PlanTask,
)
from app.core.contracts.learning import SkillConfidence
from app.core.contracts.skills import SkillLifecycleState
from app.core.gambit.skill_registry import InMemorySkillRegistry
from app.core.gambit.task_decomposer import TaskDecomposer
from app.core.gambit.workflow_engine import WorkflowEngine

if TYPE_CHECKING:
    from app.memory.manager import MemoryManager


class Planner:
    """Coordinates goal parsing, skill discovery, and plan generation."""

    def __init__(
        self,
        goal_parser: GoalParser | None = None,
        task_decomposer: TaskDecomposer | None = None,
        workflow_engine: WorkflowEngine | None = None,
        skill_registry: SkillRegistry | None = None,
        memory_manager: "MemoryManager" | None = None,
    ) -> None:
        self._goal_parser = goal_parser or GoalParser()
        self._task_decomposer = task_decomposer or TaskDecomposer()
        self._workflow_engine = workflow_engine or WorkflowEngine()
        self._skill_registry = skill_registry or InMemorySkillRegistry()
        self._memory = memory_manager

    async def plan(self, request: str) -> ExecutionPlan:
        goal = self._goal_parser.parse(request)
        skill_matches = await self._skill_registry.search(goal.raw_request)
        tasks = self._task_decomposer.decompose(goal, skill_matches)
        
        used_skill_ids = []
        used_skill_names = []
        planner_reasoning = []

        if self._memory:
            # 1. Retrieve skills
            relevant = self._memory.find_relevant_skills(
                goal=goal.summary, 
                category="general", 
                tags=["gambit"]
            )
            
            # 2. Filter & limit
            valid_skills = []
            for sr in relevant:
                skill = sr.skill
                # Reject any skill that is not ACTIVE (deprecated, archived)
                if skill.lifecycle_state != SkillLifecycleState.ACTIVE:
                    planner_reasoning.append(f"Rejected skill '{skill.name}': lifecycle_state={skill.lifecycle_state.value}.")
                    continue
                # Reject low confidence
                if skill.confidence == SkillConfidence.LOW:
                    planner_reasoning.append(f"Rejected skill '{skill.name}': Low confidence.")
                    continue
                # Reject low success rate
                total_runs = skill.success_count + skill.failure_count
                if total_runs > 0 and skill.success_rate < 0.5:
                    planner_reasoning.append(f"Rejected skill '{skill.name}': Low success rate ({skill.success_rate:.0%}).")
                    continue
                
                valid_skills.append(skill)
                if len(valid_skills) >= 3:
                    break
            
            # 3. Inject skills as PlanTasks
            for skill in valid_skills:
                used_skill_ids.append(skill.skill_id)
                used_skill_names.append(skill.name)
                planner_reasoning.append(f"Selected skill '{skill.name}': Deemed relevant and high confidence.")
                
                injected_task = PlanTask(
                    task_id=f"injected-{uuid4()}",
                    title=skill.name,
                    description=skill.description,
                    kind=tasks[0].kind if tasks else "skill_injection",
                    origin="skill_memory"
                )
                tasks.insert(0, injected_task)
        else:
            planner_reasoning.append("No memory manager provided. Skill retrieval skipped.")

        workflow = self._workflow_engine.build(tasks)

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
