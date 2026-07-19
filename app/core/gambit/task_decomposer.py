from __future__ import annotations

from uuid import uuid4

from app.core.contracts.planning import (
    Goal,
    GoalComplexity,
    PlanTask,
    RouterRequest,
    SkillMatch,
    TaskKind,
    TaskStatus,
)


class TaskDecomposer:
    """Decomposes normalized goals into runtime-executable task descriptions."""

    def decompose(self, goal: Goal, skill_matches: list[SkillMatch]) -> list[PlanTask]:
        tasks = [
            self._task(
                title="Understand goal and constraints",
                kind=TaskKind.UNDERSTAND,
                description=f"Interpret the user goal: {goal.summary}",
                goal=goal,
                skills=skill_matches,
                status=TaskStatus.READY,
            )
        ]

        if goal.requires_long_context:
            tasks.append(
                self._task(
                    title="Retrieve relevant context",
                    kind=TaskKind.RETRIEVE_CONTEXT,
                    description="Request relevant context through memory or retrieval systems.",
                    goal=goal,
                    skills=skill_matches,
                    dependencies=[tasks[-1].task_id],
                )
            )

        plan_dependencies = [tasks[-1].task_id]
        tasks.append(
            self._task(
                title="Generate execution strategy",
                kind=TaskKind.PLAN,
                description="Produce a safe sequence of runtime actions governed by CAP.",
                goal=goal,
                skills=skill_matches,
                dependencies=plan_dependencies,
            )
        )

        tasks.append(
            self._task(
                title="Prepare runtime action package",
                kind=TaskKind.EXECUTE_VIA_RUNTIME,
                description="Convert the strategy into structured runtime tasks without executing them.",
                goal=goal,
                skills=skill_matches,
                dependencies=[tasks[-1].task_id],
            )
        )

        if goal.complexity in {GoalComplexity.MEDIUM, GoalComplexity.HIGH}:
            tasks.append(
                self._task(
                    title="Verify plan completeness",
                    kind=TaskKind.VERIFY,
                    description="Check dependencies, missing context, CAP boundaries, and expected outputs.",
                    goal=goal,
                    skills=skill_matches,
                    dependencies=[tasks[-1].task_id],
                )
            )

        tasks.append(
            self._task(
                title="Reflect on plan outcome",
                kind=TaskKind.REFLECT,
                description="Summarize lessons after runtime reports task outcomes.",
                goal=goal,
                skills=skill_matches,
                dependencies=[tasks[-1].task_id],
            )
        )
        return tasks

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
