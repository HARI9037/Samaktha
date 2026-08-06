"""Phase 9.3 — Deterministic Behavior Engine.

Decides HOW Samaktha behaves for the current interaction by evaluating
deterministic policies over the message, CAP context, visible memories, and
conversation metadata.

The engine receives context and visible memories; it never retrieves memory
directly and never learns. Personality is static — only behavior varies with
the current context. Output is a structured BehaviorDecision (enum values,
never a prompt).
"""

from __future__ import annotations

from typing import Any

from app.personality.behavior_features import BehaviorFeatures, extract_features
from app.personality.behavior_policies import (
    ChallengePolicyEvaluator,
    CollaborationPolicyEvaluator,
    ConfidencePolicyEvaluator,
    ExplanationPolicyEvaluator,
    HumorPolicyEvaluator,
    ReasoningPolicyEvaluator,
    TonePolicyEvaluator,
)
from app.personality.greeting import GreetingPolicy
from app.personality.identity import IdentityPolicy
from app.personality.models import (
    BehaviorDecision,
    CapContextView,
    ConversationMetadataView,
    VisibleMemory,
)


class BehaviorEngine:
    """Deterministic facade that produces one BehaviorDecision per message."""

    def __init__(
        self,
        identity_policy: IdentityPolicy | None = None,
        greeting_policy: GreetingPolicy | None = None,
    ) -> None:
        self._identity_policy = identity_policy or IdentityPolicy()
        self._greeting_policy = greeting_policy or GreetingPolicy()
        self._tone = TonePolicyEvaluator()
        self._challenge = ChallengePolicyEvaluator()
        self._humor = HumorPolicyEvaluator()
        self._reasoning = ReasoningPolicyEvaluator()
        self._explanation = ExplanationPolicyEvaluator()
        self._confidence = ConfidencePolicyEvaluator()
        self._collaboration = CollaborationPolicyEvaluator()

    def evaluate(
        self,
        message: str,
        *,
        cap_context: CapContextView | None = None,
        conversation_metadata: ConversationMetadataView | None = None,
        visible_memories: list[VisibleMemory] | None = None,
        greeting_decision=None,
        identity_decision=None,
    ) -> BehaviorDecision:
        """Produce the deterministic behavior decision for one interaction."""
        greeting = (
            greeting_decision
            if greeting_decision is not None
            else self._greeting_policy.evaluate(message)
        )
        identity = (
            identity_decision
            if identity_decision is not None
            else self._identity_policy.evaluate(message)
        )
        features = extract_features(
            message=message,
            cap_context=cap_context,
            conversation_metadata=conversation_metadata,
            visible_memories=visible_memories,
            is_greeting=greeting.is_greeting,
            is_identity_query=identity.is_identity_query,
        )
        return BehaviorDecision(
            tone=self._tone.evaluate(features),
            challenge=self._challenge.evaluate(features),
            humor=self._humor.evaluate(features),
            reasoning=self._reasoning.evaluate(features),
            explanation=self._explanation.evaluate(features),
            confidence=self._confidence.evaluate(features),
            collaboration=self._collaboration.evaluate(features),
        )
