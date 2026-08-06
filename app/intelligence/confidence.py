from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ConfidenceDomains:
    evidence: float = 0.0
    retrieval: float = 0.0
    reasoning: float = 0.0
    execution: float = 0.0
    memory: float = 0.0
    learning: float = 0.0


@dataclass(frozen=True, slots=True)
class ConfidenceSnapshot:
    domains: ConfidenceDomains
    rationale: tuple[str, ...] = field(default_factory=tuple)

