"""Phase 9.3 — Deterministic behavior policy evaluators.

Each evaluator maps the fixed BehaviorFeatures to one enum value. Pure
functions of their input: no randomness, no LLM, no prompts.

The core personality is static — these policies only change how Samaktha
behaves for the current interaction.
"""

from __future__ import annotations

from app.personality.behavior_features import BehaviorFeatures
from app.personality.models import (
    ChallengePolicy,
    CollaborationPolicy,
    ConfidencePolicy,
    ExplanationPolicy,
    HumorPolicy,
    ReasoningPolicy,
    TonePolicy,
)


class TonePolicyEvaluator:
    """Select the interaction tone (professional / casual / serious / encouraging)."""

    def evaluate(self, features: BehaviorFeatures) -> TonePolicy:
        if (
            features.serious
            or features.requires_approval
            or features.high_risk
            or features.sensitive
        ):
            return TonePolicy.SERIOUS
        if features.is_greeting or features.casual:
            return TonePolicy.CASUAL
        if features.first_interaction:
            return TonePolicy.ENCOURAGING
        return TonePolicy.PROFESSIONAL


class ChallengePolicyEvaluator:
    """Select how strongly to challenge assumptions.

    Samaktha never blindly agrees, so the default is NORMAL. Greetings and
    brief factual requests are not challenged; decisions, strategies and
    serious topics are challenged hard.
    """

    def evaluate(self, features: BehaviorFeatures) -> ChallengePolicy:
        if features.is_greeting or features.is_identity_query:
            return ChallengePolicy.NONE
        if features.brief_request:
            return ChallengePolicy.NONE
        if features.decision_seeking or features.strategic or features.serious:
            return ChallengePolicy.HIGH
        if features.brainstorming:
            return ChallengePolicy.LIGHT
        if features.casual:
            return ChallengePolicy.LIGHT
        return ChallengePolicy.NORMAL


class HumorPolicyEvaluator:
    """Select the humor level.

    Serious / governed interactions disable humor entirely; casual
    interactions allow playful humor; everything else defaults to light.
    """

    def evaluate(self, features: BehaviorFeatures) -> HumorPolicy:
        if (
            features.serious
            or features.requires_approval
            or features.high_risk
            or features.sensitive
        ):
            return HumorPolicy.DISABLED
        if features.casual:
            return HumorPolicy.PLAYFUL
        return HumorPolicy.LIGHT


class ReasoningPolicyEvaluator:
    """Select the reasoning style.

    Brainstorming uses mixed reasoning (spec), explicit creative work is
    creative, planning is strategic, technical analysis is analytical.
    """

    def evaluate(self, features: BehaviorFeatures) -> ReasoningPolicy:
        if features.brainstorming:
            return ReasoningPolicy.MIXED
        if features.creative:
            return ReasoningPolicy.CREATIVE
        if features.strategic:
            return ReasoningPolicy.STRATEGIC
        if features.technical:
            return ReasoningPolicy.ANALYTICAL
        return ReasoningPolicy.MIXED


class ExplanationPolicyEvaluator:
    """Select explanation depth."""

    def evaluate(self, features: BehaviorFeatures) -> ExplanationPolicy:
        if features.brief_request or features.is_greeting:
            return ExplanationPolicy.BRIEF
        if features.technical or features.serious:
            return ExplanationPolicy.DETAILED
        return ExplanationPolicy.NORMAL


class ConfidencePolicyEvaluator:
    """Select the confidence framing.

    Samaktha never pretends certainty. Future predictions and governed,
    high-stakes topics are explicitly uncertain; user uncertainty produces a
    qualified answer; casual non-technical chatter is direct.
    """

    def evaluate(self, features: BehaviorFeatures) -> ConfidencePolicy:
        if (
            features.future_prediction
            or features.requires_approval
            or features.high_risk
            or features.sensitive
        ):
            return ConfidencePolicy.EXPLICIT_UNCERTAINTY
        if features.uncertainty:
            return ConfidencePolicy.QUALIFIED
        if features.casual and not features.technical:
            return ConfidencePolicy.DIRECT
        return ConfidencePolicy.QUALIFIED


class CollaborationPolicyEvaluator:
    """Select the collaboration posture.

    Samaktha is a collaborative partner by default; it shifts to ASSIST only
    for clear, direct execution commands outside collaborative contexts.
    """

    def evaluate(self, features: BehaviorFeatures) -> CollaborationPolicy:
        if features.is_command and not features.brainstorming and not features.strategic:
            return CollaborationPolicy.ASSIST
        return CollaborationPolicy.PARTNER
