from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.intelligence.confidence import ConfidenceDomains, ConfidenceSnapshot


@dataclass(frozen=True, slots=True)
class ReflectionSummary:
    outcome: str
    intent_comparison: str
    evidence: tuple[str, ...]
    learning_proposals: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ReflectionMetrics:
    success_rate: float = 0.0
    retry_count: int = 0
    planning_depth: int = 0
    tool_failure_rate: float = 0.0
    memory_recall_accuracy: float = 0.0
    context_utilization: float = 0.0
    hallucination_avoidance_events: int = 0
    approval_delay: int = 0
    learning_proposal_count: int = 0


@dataclass
class ReflectionEngine:
    def reflect(self, execution_report: Any) -> ReflectionSummary:
        outcome = self._classify_outcome(execution_report)
        evidence = self._extract_evidence(execution_report)
        intent_comparison = self._compare_intent(execution_report, evidence)
        proposals = self._proposal_seed(execution_report, outcome, evidence)
        return ReflectionSummary(outcome=outcome, intent_comparison=intent_comparison, evidence=tuple(evidence), learning_proposals=tuple(proposals))

    def metrics(self, execution_report: Any) -> ReflectionMetrics:
        total = max(int(getattr(execution_report, "completed_tasks", 0)) + int(getattr(execution_report, "failed_tasks", 0)), 0)
        success = int(bool(getattr(execution_report, "success", False)))
        return ReflectionMetrics(
            success_rate=float(success),
            retry_count=int(getattr(execution_report, "metadata", {}).get("retries", 0)),
            planning_depth=int(getattr(execution_report, "metadata", {}).get("planning_depth", 0)),
            tool_failure_rate=float(getattr(execution_report, "metadata", {}).get("tool_failure_rate", 0.0)),
            memory_recall_accuracy=float(getattr(execution_report, "metadata", {}).get("memory_recall_accuracy", 0.0)),
            context_utilization=float(getattr(execution_report, "metadata", {}).get("context_utilization", 0.0)),
            hallucination_avoidance_events=int(getattr(execution_report, "metadata", {}).get("hallucination_avoidance_events", 0)),
            approval_delay=int(getattr(execution_report, "metadata", {}).get("approval_delay", 0)),
            learning_proposal_count=len(self.reflect(execution_report).learning_proposals),
        )

    def _classify_outcome(self, execution_report: Any) -> str:
        if getattr(execution_report, "success", False):
            return "success"
        if getattr(execution_report, "failed_tasks", 0) and getattr(execution_report, "completed_tasks", 0):
            return "partial_success"
        if getattr(execution_report, "failed_tasks", 0):
            return "failure"
        return "inconclusive"

    def _extract_evidence(self, execution_report: Any) -> list[str]:
        evidence = []
        for item in getattr(execution_report, "results", []):
            evidence.append(str(getattr(item, "task_id", item)))
        evidence.extend(str(err) for err in getattr(execution_report, "errors", []))
        return evidence

    def _compare_intent(self, execution_report: Any, evidence: list[str]) -> str:
        goal = str(getattr(execution_report, "metadata", {}).get("goal", ""))
        return "aligned" if goal and evidence else "limited"

    def _proposal_seed(self, execution_report: Any, outcome: str, evidence: list[str]) -> list[dict[str, Any]]:
        if outcome == "inconclusive":
            return []
        return [
            {
                "kind": "learning_proposal",
                "source": "reflection",
                "evidence": evidence[:3],
                "confidence": 0.5 if outcome != "success" else 0.8,
            }
        ]

