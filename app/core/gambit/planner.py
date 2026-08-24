from __future__ import annotations

from types import SimpleNamespace
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
from app.tools.framework import ToolSelector
from app.tools.framework.validator import ToolValidator
from app.intelligence.planning import (
    AdaptivePlanningPolicy,
    ExplainabilityEngine,
    FailurePatternLibrary,
    PlanOptimizer,
    PlanningContext,
    PlanningMetricsCollector,
)


class _CapabilityRegistryView:
    """Presents a CapabilityRegistry to the ToolSelector as a tool registry.

    Each installed capability domain is exposed as a tool whose declared
    capability is the domain itself, so GAMBIT can select tools by
    capability without hardcoding any tool id.
    """

    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry

    def list_tools(self) -> list[SimpleNamespace]:
        tools: list[SimpleNamespace] = []
        for entry in self._registry.entries():
            if not entry.tool_id or not self._registry.is_installed(entry.domain):
                continue
            tools.append(
                SimpleNamespace(
                    info=SimpleNamespace(
                        tool_id=entry.tool_id,
                        capabilities=[entry.domain, entry.tool_id],
                    )
                )
            )
        return tools


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
        intelligence_manager: object | None = None,
    ) -> None:
        self._goal_parser = goal_parser or GoalParser()
        self._task_decomposer = task_decomposer or TaskDecomposer()
        self._plan_builder = plan_builder or PlanBuilder()
        self._skill_registry = skill_registry or InMemorySkillRegistry()
        self._capability_registry = capability_registry or CapabilityRegistry.default()
        self._tool_selector = ToolSelector(_CapabilityRegistryView(self._capability_registry))
        self._memory_manager = memory_manager
        self._intelligence_manager = intelligence_manager
        self._plan_optimizer = PlanOptimizer()
        self._explainability = ExplainabilityEngine()
        self._failure_patterns = FailurePatternLibrary()
        self._adaptive_policy = AdaptivePlanningPolicy()
        self._planning_metrics = PlanningMetricsCollector()
        self._tool_validator = ToolValidator()

    def _resolve_tool_ids(self, tasks: list[PlanTask]) -> None:
        """Fill in concrete tool ids for capability-based tool tasks.

        Tasks carry a capability/domain hint but no hardcoded tool id;
        GAMBIT selects the tool through the ToolSelector (data-driven).
        """
        for task in tasks:
            if task.execution_action_type != "tool":
                continue
            metadata = task.metadata
            if metadata.get("tool") is not None:
                continue
            domain = metadata.get("domain")
            capability = metadata.get("capability")
            selected = self._tool_selector.select(domain or capability or "")
            if selected is not None:
                metadata["tool"] = selected
                log.info("Planner resolved capability %s -> tool %s", domain or capability, selected)

    def _tool_input_errors(self, tasks: list[PlanTask]) -> list[str]:
        """Validate resolved plan inputs against the production ToolRegistry."""
        source = self._capability_registry.source_registry
        if source is None:
            return []
        errors: list[str] = []
        for task in tasks:
            if task.execution_action_type != "tool":
                continue
            tool_id = task.metadata.get("tool")
            if not tool_id:
                errors.append("tool: no registered implementation resolved")
                continue
            info = source.info_for(tool_id)
            if info is None or not info.available:
                errors.append(f"{tool_id}: registered implementation unavailable")
                continue
            action = str(task.metadata.get("action") or "")
            if info.supported_actions and action not in info.supported_actions:
                errors.append(f"{tool_id}: unsupported action '{action}'")
                continue
            arguments = dict(task.metadata.get("args") or {})
            if action:
                arguments.setdefault("action", action)
            errors.extend(
                self._tool_validator.validate_arguments(
                    tool_id, arguments, info.input_schema
                )
            )
        return errors

    @staticmethod
    def _personality_directive(personality_context: dict) -> str:
        """Render a compact, deterministic personality directive string."""
        profile_id = personality_context.get("profile_id", "unknown")
        parts = [f"personality={profile_id}"]
        name = personality_context.get("name")
        if name:
            parts.append(f"name={name}")
        for key in ("tone", "reasoning", "explanation"):
            value = personality_context.get(key)
            if value:
                parts.append(f"{key}={value}")
        return "; ".join(parts)

    async def plan(self, request: str, planning_context: PlanningContext | None = None, personality_context: dict | None = None) -> ExecutionPlan:
        """Build an ExecutionPlan directly (no capability check).

        Prefer plan_with_capability_check() for the production path so that
        unknown capabilities stop before the Workflow Engine.
        """
        goal = self._goal_parser.parse(request)
        skill_matches = await self._skill_registry.search(goal.raw_request)
        tasks = self._task_decomposer.decompose(goal, skill_matches)
        if planning_context is not None:
            tasks = self._plan_optimizer.optimize(tasks, planning_context)
        self._resolve_tool_ids(tasks)
        
        used_skill_ids = []
        used_skill_names = []
        planner_reasoning = []

        if planning_context is not None:
            planner_reasoning.extend(self._explainability.explain_plan(
                SimpleNamespace(used_skill_names=[], planner_reasoning=[]),
                planning_context,
            ))
            planner_reasoning.append(
                f"Retrieved {len(planning_context.bundle.evidence)} evidence items for planning."
            )
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
            planner_reasoning.append("No memory manager provided")

        notes = [
            "GAMBIT produced a plan only; runtime must execute it.",
            "Every runtime action must pass through CAP before execution.",
            "Model selection must be requested through the Router.",
        ]
        if personality_context:
            directive = self._personality_directive(personality_context)
            planner_reasoning.append(f"Personality directive applied: {directive}.")
            notes.insert(0, f"Active personality: {directive}.")

        workflow = self._plan_builder.build(tasks)
        if planning_context is not None:
            self._planning_metrics.record(
                planning_depth=len(tasks),
                retrieval_latency_ms=0.0,
                optimization_savings=max(0, len(skill_matches) - len(tasks)),
                skill_reuse_rate=1.0 if used_skill_ids else 0.0,
                reflection_reuse=len(planning_context.explanations),
                confidence_evolution=planning_context.confidence.get("learning", 0.0),
                cross_session_recall=sum(1 for e in planning_context.bundle.evidence if e.source == "session_history"),
                parallel_branch_count=sum(1 for t in tasks if t.dependencies == []),
            )

        return ExecutionPlan(
            plan_id=f"plan-{uuid4()}",
            goal=goal,
            tasks=tasks,
            workflow=workflow,
            router_request=self._router_request_for_goal(goal),
            skill_matches=skill_matches,
            notes=notes,
            used_skill_ids=used_skill_ids,
            used_skill_names=used_skill_names,
            planner_reasoning=planner_reasoning,
        )

    async def plan_with_capability_check(self, request: str, planning_context: PlanningContext | None = None, personality_context: dict | None = None) -> PlannerResult:
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

        if goal.missing_arguments:
            return PlannerResult(
                status=PlannerStatus.NEEDS_INPUT,
                required_capability=required_domain,
                missing_arguments=list(goal.missing_arguments),
            )

        # Capability is available (or not required) — build the full plan.
        skill_matches = await self._skill_registry.search(goal.raw_request)
        tasks = self._task_decomposer.decompose(goal, skill_matches)
        if planning_context is not None:
            tasks = self._plan_optimizer.optimize(tasks, planning_context)
        self._resolve_tool_ids(tasks)
        input_errors = self._tool_input_errors(tasks)
        if input_errors:
            return PlannerResult(
                status=PlannerStatus.NEEDS_INPUT,
                required_capability=required_domain,
                missing_arguments=input_errors,
            )

        used_skill_ids: list[str] = []
        used_skill_names: list[str] = []
        planner_reasoning: list[str] = []

        if planning_context is not None:
            planner_reasoning.extend(planning_context.explanations)
            planner_reasoning.append(self._explainability.explain_confidence(planning_context.confidence, planning_context))
            planner_reasoning.append(
                f"Retrieved {len(planning_context.bundle.evidence)} evidence items for planning."
            )
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
                if used_skill_ids:
                    planner_reasoning.append(f"Injected {len(used_skill_ids)} relevant skills from memory.")
                else:
                    planner_reasoning.append("Capability registry check passed; no relevant skills found.")
            except Exception:
                planner_reasoning.append("Capability registry check passed; memory skill injection failed.")
        else:
            planner_reasoning.append("Capability registry check passed.")

        notes = [
            "GAMBIT produced a plan only; runtime must execute it.",
            "Every runtime action must pass through CAP before execution.",
            "Model selection must be requested through the Router.",
        ]
        if personality_context:
            directive = self._personality_directive(personality_context)
            planner_reasoning.append(f"Personality directive applied: {directive}.")
            notes.insert(0, f"Active personality: {directive}.")

        workflow = self._plan_builder.build(tasks)

        plan = ExecutionPlan(
            plan_id=f"plan-{uuid4()}",
            goal=goal,
            tasks=tasks,
            workflow=workflow,
            router_request=self._router_request_for_goal(goal),
            skill_matches=skill_matches,
            notes=notes,
            used_skill_ids=used_skill_ids,
            used_skill_names=used_skill_names,
            planner_reasoning=planner_reasoning,
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
