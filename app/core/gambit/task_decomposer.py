from __future__ import annotations

import logging
from uuid import uuid4

from app.core.contracts.planning import (
    Goal,
    GoalComplexity,
    GoalIntent,
    PlanTask,
    RouterRequest,
    SkillMatch,
    TaskKind,
    TaskStatus,
)

log = logging.getLogger(__name__)


class TaskDecomposer:
    """Decomposes normalized goals into runtime-executable task sequences.

    Intent-to-plan mapping:
      READ_RESOURCE     → [UNDERSTAND, tool:resolver(read), EXECUTE_VIA_RUNTIME(text_generation), REFLECT]
                          ResolverTool selects the specific handler (pdf, image, filesystem) after planning.
      LIST_DIRECTORY    → [UNDERSTAND, tool:resolver(list), REFLECT]  — no LLM required
      SEARCH_MEMORY     → [UNDERSTAND, tool:memory(search), EXECUTE_VIA_RUNTIME, REFLECT]
      OPERATE_WINDOWS   → [UNDERSTAND, tool:windows(action), REFLECT]
      GENERATE_CODE     → [UNDERSTAND, EXECUTE_VIA_RUNTIME(text_generation), REFLECT]
      ANSWER_QUESTION   → [UNDERSTAND, EXECUTE_VIA_RUNTIME(text_generation), REFLECT]
    """

    def decompose(self, goal: Goal, skill_matches: list[SkillMatch]) -> list[PlanTask]:
        intent = goal.intent

        # Shared first task for all paths
        understand = self._task(
            title="Understand goal and constraints",
            kind=TaskKind.UNDERSTAND,
            description=f"Interpret the user goal: {goal.summary}",
            goal=goal,
            skills=skill_matches,
            status=TaskStatus.READY,
        )
        tasks: list[PlanTask] = [understand]
        prev_id = understand.task_id

        # ── Intent branch ──────────────────────────────────────────────────

        if intent in (
            GoalIntent.READ_RESOURCE,
            GoalIntent.SEARCH_RESOURCE,
            GoalIntent.DELETE_RESOURCE,
            GoalIntent.MOVE_RESOURCE,
            GoalIntent.COPY_RESOURCE,
            GoalIntent.RENAME_RESOURCE,
        ):
            action_map = {
                GoalIntent.READ_RESOURCE: "read",
                GoalIntent.SEARCH_RESOURCE: "search",
                GoalIntent.DELETE_RESOURCE: "delete",
                GoalIntent.MOVE_RESOURCE: "move",
                GoalIntent.COPY_RESOURCE: "copy",
                GoalIntent.RENAME_RESOURCE: "move",
            }
            action = action_map[intent]
            
            resolver_task = self._tool_task(
                title=f"Resolve and {action} resource",
                tool="resolver",
                action=action,
                args={"path": goal.target_path or ""},
                goal=goal,
                dependencies=[prev_id],
            )
            tasks.append(resolver_task)
            prev_id = resolver_task.task_id

            # Only read and search need LLM summarization; mutations just reflect.
            if intent in (GoalIntent.READ_RESOURCE, GoalIntent.SEARCH_RESOURCE):
                llm_task = self._task(
                    title=f"Reason over {action} results",
                    kind=TaskKind.EXECUTE_VIA_RUNTIME,
                    description=f"Use the {action} output as context to summarize or answer the user request.",
                    goal=goal,
                    skills=skill_matches,
                    dependencies=[prev_id],
                )
                llm_task.execution_action_type = "text_generation"
                tasks.append(llm_task)
                prev_id = llm_task.task_id

        elif intent == GoalIntent.LIST_DIRECTORY:
            list_task = self._tool_task(
                title="List directory contents",
                tool="resolver",
                action="list",
                args={"path": goal.target_path or "."},
                goal=goal,
                dependencies=[prev_id],
            )
            tasks.append(list_task)
            prev_id = list_task.task_id

        elif intent == GoalIntent.SEARCH_MEMORY:
            mem_task = self._tool_task(
                title="Search conversation and skill memory",
                tool="memory",
                action="search",
                args={"query": goal.query or goal.raw_request},
                goal=goal,
                dependencies=[prev_id],
            )
            tasks.append(mem_task)
            prev_id = mem_task.task_id

            llm_task = self._task(
                title="Synthesize memory results into response",
                kind=TaskKind.EXECUTE_VIA_RUNTIME,
                description="Combine memory results with user request and produce a response.",
                goal=goal,
                skills=skill_matches,
                dependencies=[prev_id],
            )
            llm_task.execution_action_type = "text_generation"
            tasks.append(llm_task)
            prev_id = llm_task.task_id

        elif intent == GoalIntent.OPERATE_WINDOWS:
            windows_task = self._tool_task(
                title="Execute Windows system operation",
                tool="windows",
                action=self._detect_windows_action(goal.raw_request),
                args={"query": goal.query or goal.raw_request},
                goal=goal,
                dependencies=[prev_id],
            )
            tasks.append(windows_task)
            prev_id = windows_task.task_id

        else:
            # ANSWER_QUESTION, GENERATE_CODE, and any unmatched intent
            if goal.requires_long_context:
                ctx_task = self._task(
                    title="Retrieve relevant context",
                    kind=TaskKind.RETRIEVE_CONTEXT,
                    description="Request relevant context through memory or retrieval systems.",
                    goal=goal,
                    skills=skill_matches,
                    dependencies=[prev_id],
                )
                tasks.append(ctx_task)
                prev_id = ctx_task.task_id

            llm_task = self._task(
                title="Generate LLM response",
                kind=TaskKind.EXECUTE_VIA_RUNTIME,
                description="Call the language model to produce a direct answer.",
                goal=goal,
                skills=skill_matches,
                dependencies=[prev_id],
            )
            llm_task.execution_action_type = "text_generation"
            tasks.append(llm_task)
            prev_id = llm_task.task_id

        # ── Optional verify for complex goals ────────────────────────────
        if goal.complexity in {GoalComplexity.MEDIUM, GoalComplexity.HIGH}:
            verify = self._task(
                title="Verify plan completeness",
                kind=TaskKind.VERIFY,
                description="Check dependencies, missing context, and expected outputs.",
                goal=goal,
                skills=skill_matches,
                dependencies=[prev_id],
            )
            tasks.append(verify)
            prev_id = verify.task_id

        # ── Always reflect ─────────────────────────────────────────────
        reflect = self._task(
            title="Reflect on plan outcome",
            kind=TaskKind.REFLECT,
            description="Summarize lessons after runtime reports task outcomes.",
            goal=goal,
            skills=skill_matches,
            dependencies=[prev_id],
        )
        tasks.append(reflect)

        log.info("TaskDecomposer: %d tasks created", len(tasks))
        return tasks

    # ── Helper factories ─────────────────────────────────────────────────

    def _task(
        self,
        title: str,
        kind: TaskKind,
        description: str,
        goal: Goal,
        skills: list[SkillMatch],
        dependencies: list[str] | None = None,
        status: TaskStatus = TaskStatus.PENDING,
    ) -> PlanTask:
        return PlanTask(
            task_id=f"task-{uuid4()}",
            title=title,
            kind=kind,
            description=description,
            dependencies=dependencies or [],
            suggested_skills=[
                match.skill.skill_id
                for match in skills
                if kind in match.skill.task_kinds
            ],
            router_request=self._router_request(goal, kind),
            cap_required=True,
            status=status,
        )

    def _tool_task(
        self,
        title: str,
        tool: str,
        action: str,
        args: dict,
        goal: Goal,
        dependencies: list[str] | None = None,
    ) -> PlanTask:
        """Create a tool execution task that routes through ToolExecutor."""
        task = PlanTask(
            task_id=f"task-{uuid4()}",
            title=title,
            kind=TaskKind.EXECUTE_VIA_RUNTIME,
            description=f"{tool}:{action} — {title}",
            dependencies=dependencies or [],
            cap_required=True,
            status=TaskStatus.PENDING,
            execution_action_type="tool",
            metadata={"tool": tool, "action": action, "args": args},
        )
        log.info("TaskDecomposer: created task — tool=%s action=%s args=%s", tool, action, args)
        return task

    @staticmethod
    def _detect_windows_action(request: str) -> str:
        lowered = request.lower()
        if "process" in lowered:
            return "processes"
        if "clipboard" in lowered:
            return "clipboard_get"
        return "terminal"

    @staticmethod
    def _router_request(goal: Goal, kind: TaskKind) -> RouterRequest:
        return RouterRequest(
            purpose=f"{kind.value}: {goal.summary}",
            complexity=goal.complexity,
            estimated_context_tokens=goal.estimated_context_tokens,
            requires_local_model=goal.requires_local_model,
            requires_code=goal.requires_code,
            requires_reasoning=goal.complexity == GoalComplexity.HIGH,
        )




