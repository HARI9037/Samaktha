from __future__ import annotations

from pydantic import BaseModel, Field


class RoutingPolicy(BaseModel):
    """Policy constraints that guide provider selection in the Router."""

    max_context_size: int = 128_000
    require_private_execution: bool = False
    prefer_local: bool = False
    prefer_low_cost: bool = False
    prefer_fast_response: bool = False
