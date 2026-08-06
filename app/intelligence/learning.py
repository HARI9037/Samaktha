from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.intelligence.memory_evolution import MemoryLifecycleState


@dataclass(frozen=True, slots=True)
class LearningProposal:
    proposal_id: str
    kind: str
    content: str
    evidence: tuple[str, ...]
    confidence: float
    lifecycle_state: MemoryLifecycleState = MemoryLifecycleState.CAPTURED
    version: dict[str, str] = field(default_factory=dict)


@dataclass
class LearningEngine:
    def capture(self, reflection_summary: Any) -> tuple[str, ...]:
        return tuple(getattr(reflection_summary, "evidence", ()))

    def normalize(self, captured: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(str(item).strip() for item in captured if str(item).strip()))

    def validate(self, normalized: tuple[str, ...]) -> bool:
        return bool(normalized)

    def score(self, normalized: tuple[str, ...]) -> float:
        return min(1.0, 0.2 * len(normalized))

    def classify(self, normalized: tuple[str, ...]) -> str:
        return "skill" if len(normalized) > 1 else "knowledge"

    def propose(self, reflection_summary: Any) -> tuple[LearningProposal, ...]:
        captured = self.capture(reflection_summary)
        normalized = self.normalize(captured)
        if not self.validate(normalized):
            return tuple()
        confidence = self.score(normalized)
        kind = self.classify(normalized)
        return (
            LearningProposal(
                proposal_id=f"learning-{len(normalized)}",
                kind=kind,
                content=str(getattr(reflection_summary, "intent_comparison", "")),
                evidence=normalized,
                confidence=confidence,
                lifecycle_state=MemoryLifecycleState.VALIDATED,
                version={
                    "intelligence": "17.0.1",
                    "learning": "17.0.1",
                    "reflection": "17.0.1",
                    "retrieval": "17.0.1",
                },
            ),
        )

