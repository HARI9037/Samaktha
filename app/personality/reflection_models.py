"""Phase 9.5 — Reflection data models.

Deterministic, structured observations of one completed interaction. The
ReflectionEngine produces a ReflectionReport AFTER the response exists; it
never influences the current conversation and never performs learning. This
module holds only the report shape and its value enums — no logic.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class ConversationType(StrEnum):
    """Primary deterministic classification of the interaction."""

    GREETING = "greeting"
    IDENTITY = "identity"
    CLARIFICATION = "clarification"
    CODING = "coding"
    PLANNING = "planning"
    TECHNICAL = "technical"
    CREATIVE = "creative"
    GENERAL = "general"


class MemoryUsage(StrEnum):
    """How already-retrieved memories reached the provider, if at all."""

    NONE = "none"
    VISIBLE = "visible"
    SUMMARIZED = "summarized"


class RiskLevel(StrEnum):
    """Deterministic risk observation derived from the CAP context view."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CompletionStatus(StrEnum):
    """How the completed interaction ended, observed from the response."""

    COMPLETED = "completed"
    REFUSED = "refused"
    NO_RESPONSE = "no_response"


class ReflectionReport(BaseModel):
    """Deterministic structured record of one completed interaction.

    Descriptive only — never prescriptive. Carries no provider/prompt/learning
    fields and never mutates any state.
    """

    interaction_summary: str
    conversation_type: ConversationType
    behavior_used: str
    reasoning_used: str
    memory_usage: MemoryUsage
    uncertainty_detected: bool
    clarification_requested: bool
    user_goal_detected: bool
    response_length: int
    technical_topic: bool
    creative_topic: bool
    contains_code: bool
    contains_plan: bool
    contains_questions: bool
    risk_level: RiskLevel
    approval_required: bool
    completion_status: CompletionStatus
