"""Phase 3.2 — Skill Learning contracts.

These models are produced by the LearningEngine and consumed by the Planner.
They live in contracts so any subsystem can reference them without importing
implementation code from app.core.gambit.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SkillConfidence(StrEnum):
    """Confidence level assigned to a learned SkillCandidate."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SkillCandidate(BaseModel):
    """A reusable planning pattern extracted from a successful execution."""

    skill_id: str
    title: str
    description: str
    category: str = "general"
    confidence: SkillConfidence = SkillConfidence.LOW
    source_plan_id: str = ""
    success_rate: float = 0.0
    times_observed: int = 1
    estimated_value: float = 0.0
    tags: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LearningResult(BaseModel):
    """Output produced by LearningEngine.learn().

    Contains extracted skill candidates and discarded patterns from one
    plan + report + reflection triple.  It is immutable — the Learning
    Engine never persists or modifies state.
    """

    learning_id: str
    generated_at: datetime = Field(default_factory=datetime.now)
    candidates: list[SkillCandidate] = Field(default_factory=list)
    discarded_candidates: list[SkillCandidate] = Field(default_factory=list)
    summary: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
