"""Backward-compatible exports for GAMBIT planning contracts."""

from app.core.contracts.learning import LearningResult, SkillCandidate, SkillConfidence

from app.core.contracts.skills import SkillLifecycleState, SkillRecord, SkillSearchResult
from app.core.contracts.planning import (
    ExecutionPlan,
    FailureCause,
    Goal,
    GoalComplexity,
    PlanReflection,
    PlanTask,
    ReflectionResult,
    ReplanRecommendation,
    RouterRequest,
    Skill,
    SkillMatch,
    SkillRegistry,
    TaskKind,
    TaskOutcome,
    TaskStatus,
    WorkflowStage,
    WorkflowStep,
)

__all__ = [
    "ExecutionPlan",
    "FailureCause",
    "Goal",
    "GoalComplexity",
    "LearningResult",
    "PlanReflection",
    "PlanTask",
    "ReflectionResult",
    "ReplanRecommendation",
    "RouterRequest",
    "Skill",
    "SkillCandidate",
    "SkillConfidence",
    "SkillLifecycleState",
    "SkillMatch",
    "SkillRecord",
    "SkillRegistry",
    "SkillSearchResult",
    "TaskKind",
    "TaskOutcome",
    "TaskStatus",
    "WorkflowStage",
    "WorkflowStep",
]
