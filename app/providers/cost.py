from pydantic import BaseModel


class CostEstimate(BaseModel):
    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0
    currency: str = "USD"


class CostEstimator:
    """Deterministic local cost estimator using per-million-token pricing."""

    def __init__(self, pricing_table: dict[str, dict[str, float]] | None = None) -> None:
        self._pricing_table = pricing_table or {
            "gpt-4o-mini": {"input": 0.15, "output": 0.60},
            "gpt-4o": {"input": 2.50, "output": 10.00},
            "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
            "openai/gpt-oss-120b": {"input": 0.15, "output": 0.60},
            "mock-model": {"input": 0.0, "output": 0.0},
            "local-default": {"input": 0.0, "output": 0.0},
        }

    def estimate(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> CostEstimate:
        pricing = self._pricing_table.get(model, {"input": 0.0, "output": 0.0})
        input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
        output_cost = (completion_tokens / 1_000_000) * pricing["output"]
        return CostEstimate(
            input_cost=input_cost,
            output_cost=output_cost,
            total_cost=input_cost + output_cost,
        )
