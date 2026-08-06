from __future__ import annotations

from pydantic import BaseModel


class RoutingPolicy(BaseModel):
    """Policy constraints that guide provider selection in the Router."""

    max_context_size: int = 128_000
    require_private_execution: bool = False
    prefer_local: bool = False
    prefer_low_cost: bool = False
    prefer_fast_response: bool = False
    max_latency_ms: float | None = None
    max_cost_per_1k_tokens: float | None = None
    require_context_tokens: int | None = None
