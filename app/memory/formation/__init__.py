"""Phase 8.2 — Autonomous Memory Formation.

A deterministic engine that inspects every completed interaction and
persists whatever is worth remembering — without explicit "remember this".

Layers:
    classifier — rule-based typed-memory classification (local, deterministic)
    engine — formation pipeline: classify → importance → dedup → write
"""

from app.memory.formation.classifier import Classification, MemoryClassifier
from app.memory.formation.engine import (
    MemoryFormationEngine,
    MemoryFormationResult,
)

__all__ = [
    "Classification",
    "MemoryClassifier",
    "MemoryFormationEngine",
    "MemoryFormationResult",
]
