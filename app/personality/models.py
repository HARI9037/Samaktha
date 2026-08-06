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


class ConversationIntent(StrEnum):
    """Phase 11.3 — Deterministic classification of a conversational request.

    Produced by the IntentEngine before the ResponseFormatter renders the
    answer. The formatter switches ONLY on this enum value; it never inspects
    raw text. Conversational intents only — never GoalParser task intents.
    """

    UNKNOWN = "unknown"
    GREETING = "greeting"
    GOODBYE = "goodbye"
    WHO_ARE_YOU = "who_are_you"
    WHAT_ARE_YOU = "what_are_you"
    CREATOR = "creator"
    CAPABILITIES = "capabilities"
    HELP = "help"
    MEMORY_RECALL = "memory_recall"
    DELETE_MEMORY = "delete_memory"
    ARCHITECTURE = "architecture"
    VERSION = "version"
    THANKS = "thanks"
    CONFIRMATION = "confirmation"
    NEGATION = "negation"
    COMPARISON = "comparison"


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
    content: str = ""
    provenance: str = ""
    session_id: str = ""
    confidence: float = 0.0
    freshness: str = ""


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


class TonePolicy(StrEnum):
    """Deterministic tone of the interaction (Phase 9.3)."""

    PROFESSIONAL = "professional"
    CASUAL = "casual"
    SERIOUS = "serious"
    ENCOURAGING = "encouraging"


class ChallengePolicy(StrEnum):
    """How strongly Samaktha challenges assumptions."""

    NONE = "none"
    LIGHT = "light"
    NORMAL = "normal"
    HIGH = "high"


class HumorPolicy(StrEnum):
    """Humor level for the interaction."""

    DISABLED = "disabled"
    LIGHT = "light"
    PLAYFUL = "playful"


class ReasoningPolicy(StrEnum):
    """Reasoning style for the interaction."""

    ANALYTICAL = "analytical"
    STRATEGIC = "strategic"
    CREATIVE = "creative"
    MIXED = "mixed"


class ExplanationPolicy(StrEnum):
    """Explanation depth for the interaction."""

    BRIEF = "brief"
    NORMAL = "normal"
    DETAILED = "detailed"


class ConfidencePolicy(StrEnum):
    """Confidence framing for the interaction."""

    DIRECT = "direct"
    QUALIFIED = "qualified"
    EXPLICIT_UNCERTAINTY = "explicit_uncertainty"


class CollaborationPolicy(StrEnum):
    """How Samaktha positions itself in the interaction."""

    ASSIST = "assist"
    PARTNER = "partner"


class BehaviorDecision(BaseModel):
    """Structured, deterministic behavior for the current interaction.

    Pure enum values — never a prompt. Later phases render this at the
    provider boundary. Personality is static; only these values change with
    the current context.
    """

    tone: TonePolicy
    challenge: ChallengePolicy
    humor: HumorPolicy
    reasoning: ReasoningPolicy
    explanation: ExplanationPolicy
    confidence: ConfidencePolicy
    collaboration: CollaborationPolicy = CollaborationPolicy.PARTNER


class CapContextView(BaseModel):
    """Read-only projection of CAP context (Phase 9.3 input).

    Never accesses storage; the caller builds this from CAP's context and
    governance verdicts.
    """

    workflow_phase: str | None = None
    system_context: str = ""
    recent_messages: list[str] = Field(default_factory=list)
    is_memory_recall: bool = False
    requires_approval: bool = False
    high_risk: bool = False
    sensitive: bool = False


class ConversationMetadataView(BaseModel):
    """Deterministic conversation metadata passed by the caller."""

    session_message_count: int = 0


class PersonalityEvaluation(BaseModel):
    """Complete deterministic evaluation of one user message."""

    message: str
    identity: IdentityDecision
    greeting: GreetingDecision
    profile: IdentityProfile
    behavior: BehaviorDecision
    visible_memories: list[VisibleMemory] = Field(default_factory=list)
    visibility_summary: MemoryVisibilitySummary | None = None
    visibility_rule: str | None = None
    suppressed_count: int = 0


class PromptComposition(BaseModel):
    """Deterministic final system prompt for one interaction (Phase 9.4).

    Produced only by the PromptComposer from structured personality data.
    Sections are built independently and joined in a fixed order to form
    ``system_prompt``. Pure structured text — no provider logic, no business
    decisions.
    """

    identity_section: str
    behavior_section: str
    context_section: str
    memory_section: str
    task_section: str
    system_prompt: str
