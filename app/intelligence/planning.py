from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.intelligence.context import ContextBundle, ContextEvidence


@dataclass(frozen=True, slots=True)
class PlanningContext:
    query: str
    bundle: ContextBundle
    confidence: dict[str, float] = field(default_factory=dict)
    explanations: tuple[str, ...] = ()
    failure_patterns: tuple[dict[str, Any], ...] = ()
    adaptive_strategy: str = "default"


@dataclass(frozen=True, slots=True)
class PlanningMetrics:
    planning_depth: int = 0
    retrieval_latency_ms: float = 0.0
    optimization_savings: int = 0
    skill_reuse_rate: float = 0.0
    reflection_reuse: int = 0
    confidence_evolution: float = 0.0
    cross_session_recall: int = 0
    parallel_branch_count: int = 0


class PlanOptimizer:
    def optimize(self, tasks: list[Any], context: PlanningContext | None = None) -> list[Any]:
        seen: set[tuple[str, str]] = set()
        optimized: list[Any] = []
        for task in tasks:
            key = (getattr(task, "kind", None).value if getattr(task, "kind", None) else str(getattr(task, "kind", "")), getattr(task, "description", ""))
            if key in seen:
                continue
            seen.add(key)
            optimized.append(task)
        return optimized


class ExplainabilityEngine:
    def explain_plan(self, plan: Any, context: PlanningContext | None = None) -> list[str]:
        reasons = []
        if context is not None:
            reasons.append(f"Retrieved {len(context.bundle.evidence)} evidence items for planning.")
            reasons.extend(context.explanations)
            if context.failure_patterns:
                reasons.append(f"Consulted {len(context.failure_patterns)} failure patterns.")
        if getattr(plan, "used_skill_names", None):
            reasons.append(f"Used skills: {', '.join(plan.used_skill_names)}.")
        if getattr(plan, "planner_reasoning", None):
            reasons.extend(str(x) for x in plan.planner_reasoning)
        return reasons

    def explain_task(self, task: Any, context: PlanningContext | None = None) -> str:
        if context is None:
            return f"Task {getattr(task, 'title', getattr(task, 'task_id', 'task'))} was selected deterministically."
        return (
            f"Task {getattr(task, 'title', getattr(task, 'task_id', 'task'))} was selected "
            f"from {len(context.bundle.evidence)} evidence items with adaptive strategy {context.adaptive_strategy}."
        )

    def explain_confidence(self, confidence: dict[str, float], context: PlanningContext | None = None) -> str:
        parts = [f"{k}={v:.2f}" for k, v in sorted(confidence.items())]
        return "Confidence routing: " + ", ".join(parts)


class AdaptivePlanningPolicy:
    def choose(self, context: PlanningContext) -> str:
        if len(context.bundle.evidence) >= 12:
            return "broad-retrieval"
        if context.confidence.get("retrieval", 0.0) < 0.4:
            return "broaden-retrieval"
        if context.confidence.get("reasoning", 0.0) < 0.4:
            return "simple-plan"
        return "default"


class FailurePatternLibrary:
    def __init__(self) -> None:
        self._patterns: list[dict[str, Any]] = []

    def register(self, trigger: str, evidence: list[str], mitigation: str, confidence: float) -> None:
        self._patterns.append(
            {
                "trigger": trigger,
                "evidence": tuple(evidence),
                "mitigation": mitigation,
                "confidence": confidence,
            }
        )

    def consult(self, query: str) -> tuple[dict[str, Any], ...]:
        lowered = query.lower()
        return tuple(p for p in self._patterns if p["trigger"] in lowered)


class PlanningMetricsCollector:
    def __init__(self) -> None:
        self._metrics = PlanningMetrics()

    def record(self, *, planning_depth: int = 0, retrieval_latency_ms: float = 0.0, optimization_savings: int = 0, skill_reuse_rate: float = 0.0, reflection_reuse: int = 0, confidence_evolution: float = 0.0, cross_session_recall: int = 0, parallel_branch_count: int = 0) -> None:
        self._metrics = PlanningMetrics(
            planning_depth=planning_depth,
            retrieval_latency_ms=retrieval_latency_ms,
            optimization_savings=optimization_savings,
            skill_reuse_rate=skill_reuse_rate,
            reflection_reuse=reflection_reuse,
            confidence_evolution=confidence_evolution,
            cross_session_recall=cross_session_recall,
            parallel_branch_count=parallel_branch_count,
        )

    def snapshot(self) -> PlanningMetrics:
        return self._metrics

