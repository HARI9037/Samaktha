from __future__ import annotations

from app.core.contracts.planning import Skill, SkillMatch, TaskKind


class InMemorySkillRegistry:
    """In-memory skill registry for discovery and reuse during planning."""

    def __init__(self, skills: list[Skill] | None = None) -> None:
        self._skills = skills or self._default_skills()

    async def search(self, query: str, limit: int = 5) -> list[SkillMatch]:
        lowered = query.lower()
        matches = []
        for skill in self._skills:
            score = 0
            reasons = []
            for trigger in skill.triggers:
                if trigger.lower() in lowered:
                    score += 5
                    reasons.append(f"Matched trigger: {trigger}")
            for word in skill.name.lower().split():
                if word in lowered:
                    score += 1
            if score > 0:
                matches.append(SkillMatch(skill=skill, score=score, reasons=reasons))
        return sorted(matches, key=lambda match: match.score, reverse=True)[:limit]

    def register(self, skill: Skill) -> None:
        self._skills.append(skill)

    @staticmethod
    def _default_skills() -> list[Skill]:
        return [
            Skill(
                skill_id="skill-context-synthesis",
                name="Context Synthesis",
                description="Normalize retrieved context into architectural requirements.",
                triggers=["context", "requirements", "architecture", "summarize"],
                task_kinds=[TaskKind.RETRIEVE_CONTEXT, TaskKind.PLAN],
            ),
            Skill(
                skill_id="skill-code-planning",
                name="Code Planning",
                description="Plan code changes without executing them.",
                triggers=["code", "implement", "refactor", "api", "backend"],
                task_kinds=[TaskKind.PLAN, TaskKind.VERIFY],
            ),
            Skill(
                skill_id="skill-workflow-generation",
                name="Workflow Generation",
                description="Create staged workflows for runtime execution.",
                triggers=["workflow", "automation", "orchestrate", "pipeline"],
                task_kinds=[TaskKind.PLAN, TaskKind.EXECUTE_VIA_RUNTIME],
            ),
        ]
