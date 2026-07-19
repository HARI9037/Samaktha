"""Phase 3.2 — Skill Learning Engine.

LearningEngine extracts reusable SkillCandidates from a completed execution
triple (ExecutionPlan, ExecutionReport, ReflectionResult).

It is entirely deterministic and purely analytical:
- No LLM calls.
- No external API calls.
- No randomness.
- No mutations of inputs.
- No persistence.
- No side effects.
"""
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from app.core.contracts.learning import LearningResult, SkillCandidate, SkillConfidence
from app.core.contracts.planning import (
    ExecutionPlan,
    FailureCause,
    ReflectionResult,
    ReplanRecommendation,
    TaskKind,
)
from app.core.contracts.skills import SkillRecord

if TYPE_CHECKING:
    from app.memory.manager import MemoryManager
    # Imported only for type annotations; contracts must not depend on runtime.
    from app.runtime.report import ExecutionReport

# ---------------------------------------------------------------------------
# Minimum value threshold below which a candidate is discarded.
# ---------------------------------------------------------------------------
_MIN_VALUE_THRESHOLD = 0.30

# ---------------------------------------------------------------------------
# Confidence thresholds (observations → confidence level)
# ---------------------------------------------------------------------------
_HIGH_CONFIDENCE_OBSERVATIONS = 4
_MEDIUM_CONFIDENCE_OBSERVATIONS = 2


class LearningEngine:
    """Converts successful execution patterns into reusable SkillCandidates.

    Usage::

        engine = LearningEngine()
        result = engine.learn(plan, report, reflection)
        # result.candidates contains extracted skills
        # result.discarded_candidates contains patterns below the value threshold
    """

    def learn(
        self,
        plan: ExecutionPlan,
        report: "ExecutionReport",
        reflection: ReflectionResult,
    ) -> LearningResult:
        """Analyse a completed execution and extract reusable skill patterns.

        This method never mutates its arguments.  It always returns a fresh
        ``LearningResult`` regardless of the execution outcome.
        """
        successful_patterns = self._extract_successful_patterns(plan, report, reflection)
        failed_patterns = self._extract_failed_patterns(plan, report, reflection)

        grouped = self._group_similar_tasks(successful_patterns)

        candidates: list[SkillCandidate] = []
        discarded: list[SkillCandidate] = []

        for group_key, task_dicts in grouped.items():
            candidate = self._build_candidate(
                group_key=group_key,
                task_dicts=task_dicts,
                source_plan_id=plan.plan_id,
                reflection=reflection,
            )
            candidate = self._score_candidate(candidate, task_dicts, report)

            if self._is_low_value(candidate):
                discarded.append(candidate)
            else:
                candidates.append(candidate)

        # Failed patterns also become discarded candidates (for learning what not to do)
        for pattern in failed_patterns:
            discarded.append(
                SkillCandidate(
                    skill_id=f"discarded-{uuid4()}",
                    title=pattern.get("title", "Unknown failed pattern"),
                    description=pattern.get("description", "Pattern repeatedly failed."),
                    category="failed_pattern",
                    confidence=SkillConfidence.LOW,
                    source_plan_id=plan.plan_id,
                    success_rate=0.0,
                    times_observed=pattern.get("count", 1),
                    estimated_value=0.0,
                    tags=["failed", pattern.get("kind", "unknown")],
                    metadata={"reason": "repeated_failure"},
                )
            )

        summary = self._generate_summary(candidates, discarded, reflection)

        return LearningResult(
            learning_id=f"learn-{uuid4()}",
            candidates=candidates,
            discarded_candidates=discarded,
            summary=summary,
            metadata={
                "plan_id": plan.plan_id,
                "goal_summary": plan.goal.summary,
                "success_rate": reflection.success_rate,
                "replan_recommendation": reflection.replan_recommendation,
            },
        )

    def persist_learning_result(
        self, 
        result: LearningResult, 
        memory_manager: "MemoryManager"
    ) -> None:
        """Persist high/medium confidence skills to the MemoryManager.
        
        This method is purely additive and does not mutate the LearningResult.
        """
        for candidate in result.candidates:
            if candidate.confidence in {SkillConfidence.HIGH, SkillConfidence.MEDIUM}:
                record = SkillRecord(
                    skill_id=candidate.skill_id,
                    name=candidate.title,
                    description=candidate.description,
                    category=candidate.category,
                    confidence=candidate.confidence,
                    source_plan=candidate.source_plan_id,
                    tags=candidate.tags,
                    usage_count=0,
                    success_count=0,
                    failure_count=0,
                    metadata=candidate.metadata,
                )
                memory_manager.save_skill(record)

    # ------------------------------------------------------------------
    # Private helpers – extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_successful_patterns(
        plan: ExecutionPlan,
        report: "ExecutionReport",
        reflection: ReflectionResult,
    ) -> list[dict[str, Any]]:
        """Return task descriptors for tasks that completed successfully."""
        if report.completed_tasks == 0:
            return []

        completed_ids: set[str] = set(reflection.completed_task_ids) if hasattr(reflection, "completed_task_ids") else set()

        patterns: list[dict[str, Any]] = []
        for task in plan.tasks:
            # Include task if it's in completed IDs or report shows overall success with no errors
            is_completed = task.task_id in completed_ids or (
                report.success and not report.errors
            )
            if not is_completed:
                continue

            patterns.append(
                {
                    "task_id": task.task_id,
                    "title": task.title,
                    "description": task.description,
                    "kind": task.kind,
                    "action_type": task.execution_action_type,
                    "suggested_skills": task.suggested_skills,
                }
            )
        return patterns

    @staticmethod
    def _extract_failed_patterns(
        plan: ExecutionPlan,
        report: "ExecutionReport",
        reflection: ReflectionResult,
    ) -> list[dict[str, Any]]:
        """Return task descriptors for tasks that repeatedly failed."""
        repeated = set(reflection.repeated_failures)
        if not repeated and FailureCause.REPEATED_FAILURE not in reflection.failure_causes:
            return []

        patterns: list[dict[str, Any]] = []
        for task in plan.tasks:
            if task.task_id in repeated:
                patterns.append(
                    {
                        "task_id": task.task_id,
                        "title": task.title,
                        "description": task.description,
                        "kind": str(task.kind),
                        "count": 2,  # repeated = at least 2 failures
                    }
                )
        return patterns

    # ------------------------------------------------------------------
    # Private helpers – grouping
    # ------------------------------------------------------------------

    @staticmethod
    def _group_similar_tasks(
        patterns: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Group task descriptors by (kind, action_type) to identify reusable patterns."""
        groups: dict[str, list[dict[str, Any]]] = {}
        for p in patterns:
            key = f"{p.get('kind', 'unknown')}:{p.get('action_type', 'general')}"
            groups.setdefault(key, []).append(p)
        return groups

    # ------------------------------------------------------------------
    # Private helpers – candidate construction & scoring
    # ------------------------------------------------------------------

    def _build_candidate(
        self,
        group_key: str,
        task_dicts: list[dict[str, Any]],
        source_plan_id: str,
        reflection: ReflectionResult,
    ) -> SkillCandidate:
        kind_part, action_part = group_key.split(":", 1)
        times = len(task_dicts)
        confidence = self._confidence_for_observations(times)

        # Collect unique step descriptions as the reusable "steps" knowledge
        steps = list(dict.fromkeys(t["description"] for t in task_dicts))

        # Collect tags from suggested_skills across all tasks in the group
        all_tags: list[str] = []
        for t in task_dicts:
            all_tags.extend(t.get("suggested_skills", []))
        tags = list(dict.fromkeys(all_tags))  # deduplicated, order-preserved

        title = self._derive_title(kind_part, action_part, task_dicts)
        description = (
            f"Reusable pattern observed {times} time(s) during plan execution. "
            f"Task kind: {kind_part}. Action type: {action_part}."
        )

        return SkillCandidate(
            skill_id=f"skill-{uuid4()}",
            title=title,
            description=description,
            category=kind_part,
            confidence=confidence,
            source_plan_id=source_plan_id,
            success_rate=reflection.success_rate,
            times_observed=times,
            estimated_value=0.0,  # filled in by _score_candidate
            tags=tags,
            steps=steps,
            metadata={"group_key": group_key},
        )

    def _score_candidate(
        self,
        candidate: SkillCandidate,
        task_dicts: list[dict[str, Any]],
        report: "ExecutionReport",
    ) -> SkillCandidate:
        """Compute estimated_value deterministically and return updated candidate."""
        # Base value: proportion of successful tasks represented by this group
        total_tasks = max(report.completed_tasks + report.failed_tasks, 1)
        coverage = len(task_dicts) / total_tasks

        # Confidence multiplier
        conf_mult = {
            SkillConfidence.HIGH: 1.0,
            SkillConfidence.MEDIUM: 0.75,
            SkillConfidence.LOW: 0.50,
        }[candidate.confidence]

        # Penalise if the overall execution had failures
        success_bonus = candidate.success_rate

        estimated_value = round(
            (coverage * 0.4 + conf_mult * 0.4 + success_bonus * 0.2),
            4,
        )

        # Pydantic models are immutable by default so we use model_copy
        return candidate.model_copy(update={"estimated_value": estimated_value})

    # ------------------------------------------------------------------
    # Private helpers – filtering
    # ------------------------------------------------------------------

    @staticmethod
    def _is_low_value(candidate: SkillCandidate) -> bool:
        return candidate.estimated_value < _MIN_VALUE_THRESHOLD

    # ------------------------------------------------------------------
    # Private helpers – confidence
    # ------------------------------------------------------------------

    @staticmethod
    def _confidence_for_observations(n: int) -> SkillConfidence:
        """Deterministic threshold-based confidence assignment."""
        if n >= _HIGH_CONFIDENCE_OBSERVATIONS:
            return SkillConfidence.HIGH
        if n >= _MEDIUM_CONFIDENCE_OBSERVATIONS:
            return SkillConfidence.MEDIUM
        return SkillConfidence.LOW

    # ------------------------------------------------------------------
    # Private helpers – titling & summary
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_title(
        kind: str,
        action_type: str,
        task_dicts: list[dict[str, Any]],
    ) -> str:
        """Produce a deterministic human-readable title for a candidate."""
        # Use the most common task title word as a descriptor
        all_words: list[str] = []
        for t in task_dicts:
            all_words.extend(t.get("title", "").lower().split())
        # Strip common stop-words
        stopwords = {"and", "the", "a", "an", "to", "for", "of", "with", "in", "on"}
        words = [w for w in all_words if w not in stopwords and len(w) > 2]
        if words:
            top_word = Counter(words).most_common(1)[0][0].title()
        else:
            top_word = kind.title()
        return f"{top_word} ({kind} / {action_type})"

    @staticmethod
    def _generate_summary(
        candidates: list[SkillCandidate],
        discarded: list[SkillCandidate],
        reflection: ReflectionResult,
    ) -> str:
        """Produce a deterministic plain-text summary of the learning result."""
        total = len(candidates) + len(discarded)
        if total == 0:
            return "No patterns were observed. Nothing learned from this execution."

        parts: list[str] = []
        parts.append(
            f"Extracted {len(candidates)} skill candidate(s) "
            f"and discarded {len(discarded)} low-value or failed pattern(s) "
            f"from {total} observed pattern(s)."
        )

        if candidates:
            high = sum(1 for c in candidates if c.confidence == SkillConfidence.HIGH)
            med  = sum(1 for c in candidates if c.confidence == SkillConfidence.MEDIUM)
            low  = sum(1 for c in candidates if c.confidence == SkillConfidence.LOW)
            parts.append(
                f"Confidence breakdown: {high} HIGH, {med} MEDIUM, {low} LOW."
            )

        if reflection.replan_recommendation in {
            ReplanRecommendation.REPLAN_IMMEDIATELY,
            ReplanRecommendation.REPLAN_WITH_CONTEXT,
        }:
            parts.append(
                "Reflection recommends replanning; extracted patterns may inform the revised plan."
            )
        elif reflection.replan_recommendation == ReplanRecommendation.ABANDON:
            parts.append(
                "Reflection recommends abandonment; extracted patterns document failure modes only."
            )

        return " ".join(parts)
