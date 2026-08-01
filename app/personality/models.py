"""Phase 9.1 — Personality Engine data models.

Structured, deterministic models only. No prompts, no response text, no
provider logic. Response text is produced by later phases at the provider
boundary.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class IdentityIntent(StrEnum):
    """The kind of identity question the user asked about Samaktha."""

    WHO_ARE_YOU = "who_are_you"
    WHAT_ARE_YOU = "what_are_you"
    INTRODUCE_YOURSELF = "introduce_yourself"
    WHAT_CAN_YOU_DO = "what_can_you_do"


class GreetingKind(StrEnum):
    """The detected kind of greeting."""

    HI = "hi"
    HELLO = "hello"
    HEY = "hey"
    GOOD_MORNING = "good_morning"
    GOOD_AFTERNOON = "good_afternoon"
    GOOD_EVENING = "good_evening"
    HOW_ARE_YOU = "how_are_you"
    WHATS_UP = "whats_up"
    GENERIC = "generic"


class IdentityProfile(BaseModel):
    """Structured, deterministic identity of Samaktha.

    Pure structured data. Never a prompt: the temporary Phase 9.1 adapter
    converts this into provider context at the model boundary.
    """

    name: str
    mission: str
    description: str
    capabilities: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    philosophy: str


class IdentityDecision(BaseModel):
    """Result of the IdentityPolicy for one user message.

    Carries no response text — only a structured decision.
    """

    is_identity_query: bool
    intent: IdentityIntent | None = None
    matched_phrase: str | None = None
    confidence: float = 0.0


class GreetingDecision(BaseModel):
    """Result of the GreetingPolicy for one user message.

    Carries no response text — only a structured decision.
    """

    is_greeting: bool
    kind: GreetingKind | None = None
    matched_phrase: str | None = None
    confidence: float = 0.0


class VisibilityType(StrEnum):
    """Per-memory visibility decision kind (Phase 9.2)."""

    ALLOW = "allow"
    SUPPRESS = "suppress"
    SUMMARIZE = "summarize"


class PreferenceCategory(StrEnum):
    """Category of a specific preference question (rule 4)."""

    LANGUAGE = "language"
    FRAMEWORK = "framework"
    IDE = "ide"
    OPERATING_SYSTEM = "operating_system"
    TERMINAL = "terminal"
    DATABASE = "database"
    BROWSER = "browser"
    TOOL = "tool"
    THEME = "theme"
    GENERIC = "generic"


class VisibleMemory(BaseModel):
    """How one already-retrieved memory is exposed to the provider."""

    memory_id: str
    reason: str
    visibility_type: VisibilityType


class MemoryVisibilitySummary(BaseModel):
    """Deterministic aggregation that replaces >5 individually-visible
    memories. Aggregates MemoryType, Importance, Recency and Tags only —
    never embeddings, never semantic reasoning."""

    total_count: int
    primary_type: str
    type_counts: dict[str, int]
    importance_bucket: str
    recency_label: str
    top_tags: list[str]
    summary_text: str


class MemoryVisibilityRule(BaseModel):
    """Descriptor for one deterministic memory-visibility rule."""

    rule_id: str
    name: str
    description: str


class MemoryVisibilityDecision(BaseModel):
    """Result of the MemoryVisibilityPolicy for one user message.

    ``visible_memories`` lists every memory that may reach the provider (or
    that was collapsed into a summary); suppressed memories are only counted.
    """

    rule: str | None = None
    visible_memories: list[VisibleMemory] = Field(default_factory=list)
    summary: MemoryVisibilitySummary | None = None
    suppressed_count: int = 0


class PersonalityEvaluation(BaseModel):
    """Complete deterministic evaluation of one user message."""

    message: str
    identity: IdentityDecision
    greeting: GreetingDecision
    profile: IdentityProfile
    visible_memories: list[VisibleMemory] = Field(default_factory=list)
    visibility_summary: MemoryVisibilitySummary | None = None
    visibility_rule: str | None = None
    suppressed_count: int = 0
