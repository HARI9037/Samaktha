import asyncio

import pytest

from app.core.contracts.planning import GoalComplexity, RouterRequest
from app.router import (
    CapabilityRegistry,
    ModelRouter,
    ProviderCapability,
    ProviderModelRegistration,
    RouterRegistry,
    RoutingPolicy,
    ScoringEngine,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def make_request(
    purpose: str = "text_generation: hello",
    requires_code: bool = False,
    requires_reasoning: bool = False,
    requires_local_model: bool = False,
    requires_fast_response: bool = False,
    complexity: GoalComplexity = GoalComplexity.LOW,
) -> RouterRequest:
    return RouterRequest(
        purpose=purpose,
        complexity=complexity,
        estimated_context_tokens=2000,
        requires_local_model=requires_local_model,
        requires_code=requires_code,
        requires_reasoning=requires_reasoning,
        requires_fast_response=requires_fast_response,
    )


def _make_capability_registry() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    reg.register(ProviderCapability(
        provider_id="mock",
        model_id="mock-model",
        capabilities=["text_generation"],
        reasoning_score=3, coding_score=3, speed_score=10,
        privacy_score=8, cost_score=10,
    ))
    reg.register(ProviderCapability(
        provider_id="openai",
        model_id="gpt-4o-mini",
        capabilities=["text_generation", "code_generation"],
        reasoning_score=9, coding_score=9, speed_score=7,
        privacy_score=3, cost_score=4,
    ))
    reg.register(ProviderCapability(
        provider_id="local",
        model_id="llama3",
        capabilities=["text_generation"],
        reasoning_score=6, coding_score=6, speed_score=5,
        privacy_score=10, cost_score=9,
    ))
    return reg


def _make_router_registry() -> RouterRegistry:
    return RouterRegistry([
        ProviderModelRegistration(provider_id="mock", model_id="mock-model", capabilities=["text_generation"]),
        ProviderModelRegistration(provider_id="openai", model_id="gpt-4o-mini", capabilities=["text_generation", "code_generation"]),
        ProviderModelRegistration(provider_id="local", model_id="llama3", capabilities=["text_generation"]),
    ])


# ── tests ─────────────────────────────────────────────────────────────────────

def test_provider_capability_model_creation():
    cap = ProviderCapability(
        provider_id="test",
        model_id="test-model",
        capabilities=["text_generation"],
        reasoning_score=7,
        coding_score=6,
        speed_score=8,
        privacy_score=5,
        cost_score=5,
    )
    assert cap.provider_id == "test"
    assert cap.reasoning_score == 7
    assert "text_generation" in cap.capabilities


def test_scoring_engine_ranks_providers():
    engine = ScoringEngine()
    caps = [
        ProviderCapability(provider_id="slow_smart", model_id="m1", capabilities=["text_generation"],
                           reasoning_score=9, coding_score=9, speed_score=3, privacy_score=5, cost_score=5),
        ProviderCapability(provider_id="fast_simple", model_id="m2", capabilities=["text_generation"],
                           reasoning_score=4, coding_score=4, speed_score=10, privacy_score=5, cost_score=8),
    ]
    # Fast task: fast_simple should win
    fast_request = make_request(requires_fast_response=True)
    ranked = engine.rank(fast_request, caps)
    assert ranked[0].provider_id == "fast_simple"

    # Complex reasoning task: slow_smart should win
    smart_request = make_request(requires_reasoning=True, complexity=GoalComplexity.HIGH)
    ranked = engine.rank(smart_request, caps)
    assert ranked[0].provider_id == "slow_smart"


def test_private_task_prefers_local_provider():
    engine = ScoringEngine()
    cap_reg = _make_capability_registry()
    policy = RoutingPolicy(require_private_execution=True)

    request = make_request(requires_local_model=True)
    ranked = engine.rank(request, cap_reg.all(), policy)

    # "local" has the highest privacy_score (10)
    assert ranked[0].provider_id == "local"


def test_complex_coding_task_prefers_high_reasoning_provider():
    engine = ScoringEngine()
    cap_reg = _make_capability_registry()

    request = make_request(
        requires_code=True,
        requires_reasoning=True,
        complexity=GoalComplexity.HIGH,
    )
    ranked = engine.rank(request, cap_reg.all())

    # "openai" has the highest reasoning + coding scores
    assert ranked[0].provider_id == "openai"


def test_fast_simple_task_prefers_fast_provider():
    engine = ScoringEngine()
    cap_reg = _make_capability_registry()

    request = make_request(requires_fast_response=True, complexity=GoalComplexity.LOW)
    ranked = engine.rank(request, cap_reg.all())

    # "mock" has speed_score=10 — highest of the three
    assert ranked[0].provider_id == "mock"


@pytest.mark.asyncio
async def test_unknown_capability_fails_safely():
    router = ModelRouter(RouterRegistry(), _make_capability_registry())
    decision = await router.route(make_request(requires_code=True))

    # No providers registered for code_generation → safe empty decision
    assert decision.provider_id == ""
    assert decision.model_id == ""
    assert "missing_capability" in decision.constraints[0]


@pytest.mark.asyncio
async def test_router_v2_uses_scoring_when_capability_registry_present():
    router = ModelRouter(_make_router_registry(), _make_capability_registry())

    # Request that heavily favours local/private
    request = make_request(requires_local_model=True)
    decision = await router.route(request)

    assert decision.provider_id == "local"
    assert "scoring_version" in decision.metadata
    assert decision.metadata["scoring_version"] == "v0.2"


@pytest.mark.asyncio
async def test_existing_v1_flow_still_works_without_capability_registry():
    """ModelRouter with no CapabilityRegistry must behave exactly as v0.1."""
    registry = RouterRegistry([
        ProviderModelRegistration(provider_id="mock", model_id="mock-model", capabilities=["text_generation"]),
    ])
    router = ModelRouter(registry)  # no capability_registry

    decision = await router.route(make_request())
    assert decision.provider_id == "mock"
    assert decision.model_id == "mock-model"
    # v0.1 summary format preserved
    assert "Selected mock/mock-model for capability: text_generation" in decision.reasoning_summary
