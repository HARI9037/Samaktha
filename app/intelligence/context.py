from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ContextEvidence:
    item_id: str
    source: str
    content: str
    provenance: str
    confidence: float
    freshness: str
    scope: str
    selected_reason: str
    timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class ContextBundle:
    query: str
    evidence: tuple[ContextEvidence, ...]
    citations: tuple[str, ...]
    provenance: tuple[str, ...]
    confidence: float
    freshness: tuple[str, ...]
    scope: str
    memory_source: tuple[str, ...]
    version: str = "17.0.1"

