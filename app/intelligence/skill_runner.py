from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SkillExecutionPlan:
    skill_id: str
    trigger: str
    steps: tuple[str, ...]
    constraints: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class SkillRunner:
    def load_approved_skill(self, skill: dict[str, object]) -> SkillExecutionPlan:
        steps = tuple(str(step) for step in skill.get("steps", []))
        return SkillExecutionPlan(
            skill_id=str(skill["skill_id"]),
            trigger=str(skill.get("trigger", "")),
            steps=steps,
            constraints=tuple(str(c) for c in skill.get("constraints", [])),
        )

    def validate_trigger(self, plan: SkillExecutionPlan, trigger: str) -> bool:
        return trigger == plan.trigger

    def verify_constraints(self, plan: SkillExecutionPlan, context: dict[str, object]) -> bool:
        return all(constraint not in context.get("violations", []) for constraint in plan.constraints)

    def expand(self, plan: SkillExecutionPlan) -> tuple[str, ...]:
        return plan.steps

