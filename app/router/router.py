from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

log = logging.getLogger(__name__)

from app.core.contracts import RouterRequest, RoutingDecision
from app.models import ModelManager
from app.router.base import Router
from app.router.capabilities import CapabilityRegistry, ProviderCapability
from app.router.policy import RoutingPolicy
from app.router.registry import RouterRegistry
from app.router.metrics import RouterMetricsCollector, RouterMetricsSnapshot
from app.router.scoring import ScoringEngine

if TYPE_CHECKING:
    from app.providers.health import ProviderHealthChecker


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
        health_checker: Optional["ProviderHealthChecker"] = None,
        preferred_provider: str | None = None,
    ) -> None:
        self._registry = registry
        self._capability_registry = capability_registry
        self._policy = policy or RoutingPolicy()
        self._scoring = ScoringEngine()
        self._model_manager = model_manager
        self._health_checker = health_checker
        self._preferred_provider = preferred_provider
        self._metrics = RouterMetricsCollector()

    def get_metrics(self) -> RouterMetricsSnapshot:
        return self._metrics.get_metrics()

    async def route(self, request: RouterRequest, context: Optional["RuntimeContext"] = None) -> RoutingDecision:
        if context and context.trace:
            context.trace.add_event(
                source="router",
                event_type="provider.selection.started",
                purpose=request.purpose,
            )

        capability = self._capability_from_request(request)
        candidates = self._registry.candidates(capability)

        # ModelRegistry is authoritative for model capabilities. A model with
        # coding metadata can satisfy a code request even when legacy router
        # registrations only declare their base text capability.
        if not candidates and capability == "code_generation" and self._model_manager is not None:
            candidates = [
                candidate
                for candidate in self._registry.candidates("text_generation")
                if (
                    (model := self._model_manager.resolve_model(candidate.model_id))
                    is not None
                    and model.coding_score > 0
                )
            ]

        # Eligibility — a model must satisfy the request constraints (context
        # window, code/reasoning requirements) before it can be selected.
        if self._model_manager is not None:
            candidates = [
                candidate
                for candidate in candidates
                if self._model_is_eligible(candidate.model_id, request)
            ]
            if not candidates:
                self._metrics.record_decision(successful=False)
                return RoutingDecision(
                    provider_id="",
                    model_id="",
                    reasoning_summary=(
                        f"No registered model satisfies capability: {capability}"
                    ),
                    constraints=[f"model_constraints:{capability}"],
                    metadata={"capability": capability},
                )

        # Health + Cooldown — dead providers and providers cooling down from a
        # failure are never returned. This participates in routing, never
        # after it: an unavailable provider can never be selected here.
        if self._health_checker:
            candidates = [
                candidate
                for candidate in candidates
                if self._health_checker.is_available(candidate.provider_id)
            ]
            if not candidates:
                self._metrics.record_decision(successful=False)
                decision = RoutingDecision(
                    provider_id="",
                    model_id="",
                    reasoning_summary=(
                        "No registered provider is currently available"
                    ),
                    constraints=[f"health_constraints:{capability}"],
                    metadata={"capability": capability},
                )
                if context and context.trace:
                    context.trace.add_event(
                        source="router",
                        event_type="provider.selection.completed",
                        success=False
                    )
                return decision

        if not candidates:
            self._metrics.record_decision(successful=False)
            decision = RoutingDecision(
                provider_id="",
                model_id="",
                reasoning_summary=f"No registered provider supports capability: {capability}",
                constraints=[f"missing_capability:{capability}"],
                metadata={"capability": capability},
            )
            if context and context.trace:
                context.trace.add_event(
                    source="router",
                    event_type="provider.selection.completed",
                    success=False
                )
            return decision

        # Honor the configured provider when it is an eligible candidate.  The
        # scoring engine is still used when the preference is unavailable or
        # incompatible with the request.
        if self._preferred_provider:
            preferred = next(
                (candidate for candidate in candidates
                 if candidate.provider_id == self._preferred_provider),
                None,
            )
            if preferred is not None:
                self._metrics.record_decision(successful=True)
                return RoutingDecision(
                    provider_id=preferred.provider_id,
                    model_id=preferred.model_id,
                    reasoning_summary=(
                        f"Configured provider selected: "
                        f"{preferred.provider_id}/{preferred.model_id}"
                    ),
                    constraints=[],
                    metadata={"capability": capability, **preferred.metadata},
                )

        # v0.2: score candidates when capability data is available
        if self._capability_registry is not None or self._model_manager is not None:
            all_caps = self._capabilities_for_candidates(candidates)
            # Filter to only those providers that appear in our candidates list
            candidate_ids = {c.provider_id for c in candidates}
            scoreable_caps = [cap for cap in all_caps if cap.provider_id in candidate_ids]

            if scoreable_caps:
                ranked = self._scoring.rank(request, scoreable_caps, self._policy)
                if ranked:
                    best = ranked[0]
                    # Find the matching registry entry for the top-scored provider
                    matched = next(
                        (c for c in candidates
                         if c.provider_id == best.provider_id
                         and c.model_id == best.model_id),
                        candidates[0],
                    )
                    self._metrics.record_decision(successful=True)
                    decision = RoutingDecision(
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
                                 if cap.provider_id == best.provider_id
                                 and cap.model_id == best.model_id),
                                0,
                            )),
                            "latency_ms": str(next(
                                (cap.latency_ms for cap in scoreable_caps
                                 if cap.provider_id == best.provider_id
                                 and cap.model_id == best.model_id),
                                "unknown",
                            )),
                            **matched.metadata,
                        },
                    )
                    log.info(
                        "Selected Provider : %s\n"
                        "Selected Model : %s\n"
                        "Reason : %s\n"
                        "Streaming : Enabled",
                        decision.provider_id,
                        decision.model_id,
                        decision.reasoning_summary,
                    )
                    if context and context.trace:
                        context.trace.add_event(
                            source="router",
                            event_type="provider.selection.completed",
                            provider_id=decision.provider_id,
                            model_id=decision.model_id,
                            success=True
                        )
                    return decision
                self._metrics.record_decision(successful=False)
                decision = RoutingDecision(
                    provider_id="",
                    model_id="",
                    reasoning_summary="No eligible model satisfies routing constraints",
                    constraints=["routing_constraints"],
                    metadata={"capability": capability},
                )
                if context and context.trace:
                    context.trace.add_event(
                        source="router",
                        event_type="provider.selection.completed",
                        success=False
                    )
                return decision

        # v0.1 fallback: pick first matching candidate
        selected = candidates[0]
        self._metrics.record_decision(successful=True)
        decision = RoutingDecision(
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
        if context and context.trace:
            context.trace.add_event(
                source="router",
                event_type="provider.selection.completed",
                provider_id=decision.provider_id,
                model_id=decision.model_id,
                success=True
            )
        return decision

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

    def _capabilities_for_candidates(
        self,
        candidates,
    ) -> list[ProviderCapability]:
        capabilities: list[ProviderCapability] = []
        for candidate in candidates:
            registered = (
                self._capability_registry.get(
                    candidate.provider_id,
                    candidate.model_id,
                )
                if self._capability_registry is not None
                else None
            )
            model = (
                self._model_manager.resolve_model(candidate.model_id)
                if self._model_manager is not None
                else None
            )
            if model is not None:
                capabilities.append(ProviderCapability(
                    provider_id=candidate.provider_id,
                    model_id=candidate.model_id,
                    capabilities=list(candidate.capabilities),
                    reasoning_score=model.reasoning_score,
                    coding_score=model.coding_score,
                    speed_score=model.speed_score,
                    privacy_score=model.privacy_score,
                    cost_score=model.cost_score,
                    context_window=model.context_window,
                    maximum_output=model.maximum_output,
                    input_cost_per_1k=model.input_cost_per_1k,
                    output_cost_per_1k=model.output_cost_per_1k,
                    version=model.version,
                    metadata={"capability_source": model.capability_source},
                ))
            elif registered is not None:
                capabilities.append(registered)
        return capabilities

    @staticmethod
    def _capability_from_request(request: RouterRequest) -> str:
        purpose = request.purpose.lower()
        if "tool_execution" in purpose or "tool execution" in purpose:
            return "tool_execution"
        if request.requires_code:
            return "code_generation"
        return "text_generation"
