"""Phase 3.3 / 3.5 — Skill Memory contracts.

These models represent validated skills that are persisted to the Knowledge Base.
They provide a stable interface between the Learning Engine (which produces them)
and the Memory Manager (which stores them).

Phase 3.5 adds:
- SkillLifecycleState (ACTIVE, DEPRECATED, ARCHIVED)
- success_rate computed field
- last_used_at / last_updated_at timestamps
- lifecycle_state
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from app.core.contracts.learning import SkillConfidence


class SkillLifecycleState(str, Enum):
    """Deterministic lifecycle state for a persisted skill."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class SkillRecord(BaseModel):
    """A persisted skill pattern inside the Knowledge Base."""

    skill_id: str
    name: str
    description: str
    category: str
    confidence: SkillConfidence
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_used_at: Optional[datetime] = None
    source_plan: str
    source_tasks: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    success_rate: float = 0.0
    lifecycle_state: SkillLifecycleState = SkillLifecycleState.ACTIVE
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _auto_compute_success_rate(self) -> "SkillRecord":
        """Auto-compute success_rate if not explicitly set and counts are present."""
        total = self.success_count + self.failure_count
        if total > 0 and self.success_rate == 0.0:
            self.success_rate = self.success_count / total
        return self

    def recompute_success_rate(self) -> None:
        """Recompute success_rate deterministically from counts."""
        total = self.success_count + self.failure_count
        self.success_rate = (self.success_count / total) if total > 0 else 0.0

    @property
    def is_active(self) -> bool:
        return self.lifecycle_state == SkillLifecycleState.ACTIVE

    @property
    def is_deprecated(self) -> bool:
        return self.lifecycle_state == SkillLifecycleState.DEPRECATED

    @property
    def is_archived(self) -> bool:
        return self.lifecycle_state == SkillLifecycleState.ARCHIVED


class SkillSearchResult(BaseModel):
    """Result of searching the Skill Memory."""

    skill: SkillRecord
    score: float
