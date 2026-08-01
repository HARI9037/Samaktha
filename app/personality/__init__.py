"""Phase 9.1 + 9.2 — Samaktha Personality Engine.

Deterministic vertical slices: identity policy, greeting policy, the
memory-visibility gate, the engine facade, the structured IdentityProfile,
and the temporary provider-context adapter.
"""

from app.personality.engine import (
    PersonalityEngine,
    SAMAKTHA_IDENTITY_PROFILE,
    identity_to_provider_context,
)
from app.personality.greeting import GreetingPolicy
from app.personality.identity import IdentityPolicy
from app.personality.memory_visibility import (
    MAX_VISIBLE_MEMORIES,
    MemoryVisibilityPolicy,
    build_summary,
)
from app.personality.models import (
    GreetingDecision,
    GreetingKind,
    IdentityDecision,
    IdentityIntent,
    IdentityProfile,
    MemoryVisibilityDecision,
    MemoryVisibilityRule,
    MemoryVisibilitySummary,
    PersonalityEvaluation,
    PreferenceCategory,
    VisibilityType,
    VisibleMemory,
)
from app.personality.visibility_rules import (
    RULE_DOCUMENT,
    RULE_GREETING,
    RULE_IDENTITY,
    RULE_PREFERENCE,
    RULE_PROFILE,
    RULE_PROJECT,
    RULE_TECHNICAL,
    RULE_WORKFLOW,
    MemoryView,
    RuleMatch,
    evaluate_visibility,
    normalize_item,
)

__all__ = [
    "PersonalityEngine",
    "SAMAKTHA_IDENTITY_PROFILE",
    "identity_to_provider_context",
    "GreetingPolicy",
    "IdentityPolicy",
    "GreetingDecision",
    "GreetingKind",
    "IdentityDecision",
    "IdentityIntent",
    "IdentityProfile",
    "PersonalityEvaluation",
    "MemoryVisibilityPolicy",
    "MAX_VISIBLE_MEMORIES",
    "build_summary",
    "MemoryVisibilityDecision",
    "MemoryVisibilityRule",
    "MemoryVisibilitySummary",
    "PreferenceCategory",
    "VisibilityType",
    "VisibleMemory",
    "RULE_DOCUMENT",
    "RULE_GREETING",
    "RULE_IDENTITY",
    "RULE_PREFERENCE",
    "RULE_PROFILE",
    "RULE_PROJECT",
    "RULE_TECHNICAL",
    "RULE_WORKFLOW",
    "MemoryView",
    "RuleMatch",
    "evaluate_visibility",
    "normalize_item",
]
