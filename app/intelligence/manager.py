from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.intelligence.context import ContextBundle
from app.intelligence.learning import LearningEngine, LearningProposal
from app.intelligence.planning import FailurePatternLibrary, PlanningContext
from app.intelligence.reflection import ReflectionEngine, ReflectionSummary
from app.intelligence.retrieval import RetrievalEngine
from app.core.contracts.memory import MemoryAccessContext


@dataclass
class IntelligenceManager:
    retrieval_engine: RetrievalEngine
    reflection_engine: ReflectionEngine
    learning_engine: LearningEngine
    cap: Any | None = None
    memory_controller: Any | None = None
    failure_patterns: FailurePatternLibrary = field(default_factory=FailurePatternLibrary)
    learning_budget: dict[str, int] = field(default_factory=lambda: {
        "max_reflections": 10,
        "max_proposals": 10,
        "max_retrieval_depth": 10,
        "max_memory_writes": 10,
        "max_indexing_operations": 10,
    })
    intelligence_version: str = "17.0.1"

    def retrieve(
        self, query: str, *, session_id: str | None = None, top_k: int = 10,
        access_context: MemoryAccessContext | None = None,
    ) -> ContextBundle:
        return self.retrieval_engine.assemble_context(
            query, session_id=session_id, top_k=top_k,
            access_context=access_context,
        )

    def assemble_context(
        self, query: str, *, session_id: str | None = None, top_k: int = 10,
        access_context: MemoryAccessContext | None = None,
    ) -> ContextBundle:
        return self.retrieve(
            query, session_id=session_id, top_k=top_k,
            access_context=access_context,
        )

    def reflect(self, execution_report: Any) -> ReflectionSummary:
        return self.reflection_engine.reflect(execution_report)

    def learn(self, reflection_summary: Any) -> tuple[LearningProposal, ...]:
        return self.learning_engine.propose(reflection_summary)

    def propose(self, reflection_summary: Any) -> tuple[LearningProposal, ...]:
        return self.learn(reflection_summary)

    def build_planning_context(
        self,
        query: str,
        *,
        session_id: str | None = None,
        top_k: int = 10,
        access_context: MemoryAccessContext | None = None,
    ) -> PlanningContext:
        bundle = self.retrieve(
            query, session_id=session_id, top_k=top_k,
            access_context=access_context,
        )
        confidence = {
            "retrieval": bundle.confidence,
            "reasoning": 0.5 if bundle.evidence else 0.0,
            "execution": 0.5,
            "memory": bundle.confidence,
            "learning": 0.5 if bundle.evidence else 0.0,
            "evidence": bundle.confidence,
        }
        patterns = self.failure_patterns.consult(query)
        explanations = tuple(e.selected_reason for e in bundle.evidence[:5])
        strategy = "broad-retrieval" if len(bundle.evidence) >= 12 else "default"
        return PlanningContext(
            query=query,
            bundle=bundle,
            confidence=confidence,
            explanations=explanations,
            failure_patterns=patterns,
            adaptive_strategy=strategy,
        )

    def dispatch_event(self, event_name: str, payload: Any) -> Any:
        if event_name == "RuntimeFinished":
            summary = self.reflect(payload)
            return self.learn(summary)
        if event_name == "ReflectionRequested":
            return self.reflect(payload)
        if event_name == "LearningProposalCreated":
            return self.learn(payload)
        return None
