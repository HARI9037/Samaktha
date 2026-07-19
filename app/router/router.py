from __future__ import annotations

from typing import Optional

from app.core.contracts import RouterRequest, RoutingDecision
from app.models import ModelManager
from app.router.base import Router
from app.router.capabilities import CapabilityRegistry
from app.router.policy import RoutingPolicy
from app.router.registry import RouterRegistry
from app.router.scoring import ScoringEngine


class ModelRouter(Router):
    """Intelligent model router that uses capability scoring when available.

    v0.2 behaviour:
    - When a CapabilityRegistry is provided, candidates are ranked by ScoringEngine
      before selecting the top match.
    - When no CapabilityRegistry is provided, falls back to the deterministic v0.1
      capability-matching behaviour — keeping full backward compatibility.
    """

    def __init__(
        self,
        registry: RouterRegistry,
        capability_registry: Optional[CapabilityRegistry] = None,
        policy: Optional[RoutingPolicy] = None,
        model_manager: Optional[ModelManager] = None,
    ) -> None:
        self._registry = registry
        self._capability_registry = capability_registry
        self._policy = policy or RoutingPolicy()
        self._scoring = ScoringEngine()
        self._model_manager = model_manager

    async def route(self, request: RouterRequest) -> RoutingDecision:
        capability = self._capability_from_request(request)
        candidates = self._registry.candidates(capability)

        if self._model_manager is not None:
            candidates = [
                candidate
                for candidate in candidates
                if self._model_is_eligible(candidate.model_id, request)
            ]
            if not candidates:
                return RoutingDecision(
                    provider_id="",
                    model_id="",
                    reasoning_summary=(
                        f"No registered model satisfies capability: {capability}"
                    ),
                    constraints=[f"model_constraints:{capability}"],
                    metadata={"capability": capability},
                )

        if not candidates:
            return RoutingDecision(
                provider_id="",
                model_id="",
                reasoning_summary=f"No registered provider supports capability: {capability}",
                constraints=[f"missing_capability:{capability}"],
                metadata={"capability": capability},
            )

        # v0.2: score candidates when capability data is available
        if self._capability_registry is not None:
            all_caps = self._capability_registry.all()
            # Filter to only those providers that appear in our candidates list
            candidate_ids = {c.provider_id for c in candidates}
            scoreable_caps = [cap for cap in all_caps if cap.provider_id in candidate_ids]

            if scoreable_caps:
                ranked = self._scoring.rank(request, scoreable_caps, self._policy)
                if ranked:
                    best = ranked[0]
                    # Find the matching registry entry for the top-scored provider
                    matched = next(
                        (c for c in candidates if c.provider_id == best.provider_id),
                        candidates[0],
                    )
                    return RoutingDecision(
                        provider_id=matched.provider_id,
                        model_id=matched.model_id,
                        reasoning_summary=(
                            f"Scored selection: {matched.provider_id}/{matched.model_id} "
                            f"(score={best.score}) for capability: {capability}. "
                            f"Factors: {'; '.join(best.reasons[:3])}"
                        ),
                        constraints=[],
                        metadata={
                            "capability": capability,
                            "score": str(best.score),
                            "scoring_version": "v0.2",
                            "context_window": str(next(
                                (cap.context_window for cap in scoreable_caps
                                 if cap.provider_id == best.provider_id),
                                0,
                            )),
                            "latency_ms": str(next(
                                (cap.latency_ms for cap in scoreable_caps
                                 if cap.provider_id == best.provider_id),
                                "unknown",
                            )),
                            **matched.metadata,
                        },
                    )
                return RoutingDecision(
                    provider_id="",
                    model_id="",
                    reasoning_summary="No eligible model satisfies routing constraints",
                    constraints=["routing_constraints"],
                    metadata={"capability": capability},
                )

        # v0.1 fallback: pick first matching candidate
        selected = candidates[0]
        return RoutingDecision(
            provider_id=selected.provider_id,
            model_id=selected.model_id,
            reasoning_summary=(
                f"Selected {selected.provider_id}/{selected.model_id} "
                f"for capability: {capability}"
            ),
            constraints=[],
            metadata={
                "capability": capability,
                **selected.metadata,
            },
        )

    def _model_is_eligible(self, model_id: str, request: RouterRequest) -> bool:
        model = self._model_manager.resolve_model(model_id)
        if model is None:
            return True
        if model.context_window < request.estimated_context_tokens:
            return False
        if request.requires_code and model.coding_score <= 0:
            return False
        if request.requires_reasoning and model.reasoning_score <= 0:
            return False
        return True

    @staticmethod
    def _capability_from_request(request: RouterRequest) -> str:
        purpose = request.purpose.lower()
        if "tool_execution" in purpose or "tool execution" in purpose:
            return "tool_execution"
        if request.requires_code:
            return "code_generation"
        return "text_generation"
