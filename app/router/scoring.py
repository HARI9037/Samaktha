from __future__ import annotations

from typing import List

from pydantic import BaseModel

from app.core.contracts.planning import GoalComplexity, RouterRequest
from app.router.capabilities import ProviderCapability
from app.router.policy import RoutingPolicy


class ProviderScore(BaseModel):
    """Computed suitability score for one provider/model pair."""

    provider_id: str
    model_id: str
    score: int
    reasons: List[str]


class ScoringEngine:
    """Deterministic scoring engine that ranks providers for a given RouterRequest.

    All scoring logic is pure arithmetic — no LLM calls, no network access.
    Higher score = more suitable for the request.
    """

    # Weight constants (relative importance of each dimension).
    _BASE_WEIGHT = 1
    _CODE_WEIGHT = 3
    _REASONING_WEIGHT = 3
    _SPEED_WEIGHT = 2
    _PRIVACY_WEIGHT = 5   # privacy is a hard-leaning constraint
    _COST_WEIGHT = 2

    def rank(
        self,
        request: RouterRequest,
        capabilities: List[ProviderCapability],
        policy: RoutingPolicy | None = None,
    ) -> List[ProviderScore]:
        """Return capabilities ranked from most to least suitable."""
        policy = policy or RoutingPolicy()
        scored = [self._score(request, cap, policy) for cap in capabilities]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored

    def _score(
        self,
        request: RouterRequest,
        cap: ProviderCapability,
        policy: RoutingPolicy,
    ) -> ProviderScore:
        score = 0
        reasons: List[str] = []

        # --- Base capability presence (always rewarded)
        score += cap.speed_score * self._BASE_WEIGHT

        # --- Code requirements
        if request.requires_code:
            weight = self._CODE_WEIGHT * (2 if request.complexity == GoalComplexity.HIGH else 1)
            contribution = cap.coding_score * weight
            score += contribution
            reasons.append(f"coding_score={cap.coding_score} (weight={weight})")

        # --- Reasoning requirements
        if request.requires_reasoning or request.complexity == GoalComplexity.HIGH:
            weight = self._REASONING_WEIGHT * (2 if request.complexity == GoalComplexity.HIGH else 1)
            contribution = cap.reasoning_score * weight
            score += contribution
            reasons.append(f"reasoning_score={cap.reasoning_score} (weight={weight})")

        # --- Speed preference
        fast_preferred = request.requires_fast_response or policy.prefer_fast_response
        if fast_preferred:
            contribution = cap.speed_score * self._SPEED_WEIGHT
            score += contribution
            reasons.append(f"speed_score={cap.speed_score} (weight={self._SPEED_WEIGHT})")

        # --- Privacy / local model requirement
        local_required = request.requires_local_model or policy.require_private_execution or policy.prefer_local
        if local_required:
            contribution = cap.privacy_score * self._PRIVACY_WEIGHT
            score += contribution
            reasons.append(f"privacy_score={cap.privacy_score} (weight={self._PRIVACY_WEIGHT})")
            # Heavy penalty if privacy score is too low (< 5) when privacy is required
            if cap.privacy_score < 5:
                score -= 50
                reasons.append("penalty: low privacy score for private request")

        # --- Cost preference
        if policy.prefer_low_cost:
            contribution = cap.cost_score * self._COST_WEIGHT
            score += contribution
            reasons.append(f"cost_score={cap.cost_score} (weight={self._COST_WEIGHT})")

        if not reasons:
            reasons.append(f"base speed_score={cap.speed_score}")

        return ProviderScore(
            provider_id=cap.provider_id,
            model_id=cap.model_id,
            score=score,
            reasons=reasons,
        )
