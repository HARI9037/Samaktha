from datetime import datetime

from pydantic import BaseModel

from app.providers.models import ProviderResponse


class ProviderMetrics(BaseModel):
    provider_id: str
    requests: int = 0
    successes: int = 0
    failures: int = 0
    average_latency_ms: float = 0.0
    average_tokens: float = 0.0
    estimated_spend: float = 0.0
    last_success: datetime | None = None
    last_failure: datetime | None = None


class ProviderMetricsStore:
    """In-memory provider runtime statistics."""

    def __init__(self) -> None:
        self._metrics: dict[str, ProviderMetrics] = {}

    def record(self, provider_id: str, response: ProviderResponse) -> None:
        metrics = self._metrics.setdefault(
            provider_id,
            ProviderMetrics(provider_id=provider_id),
        )
        metrics.requests += 1
        if response.success:
            metrics.successes += 1
            metrics.last_success = response.usage.get("response_timestamp")
        else:
            metrics.failures += 1
            metrics.last_failure = response.usage.get("response_timestamp")

        latency = response.latency_ms or 0.0
        tokens = float(response.usage.get("total_tokens", 0) or 0)
        metrics.average_latency_ms = self._average(
            metrics.average_latency_ms,
            metrics.requests,
            latency,
        )
        metrics.average_tokens = self._average(
            metrics.average_tokens,
            metrics.requests,
            tokens,
        )
        metrics.estimated_spend += float(response.cost.get("total_cost", 0.0) or 0.0)

    def get(self, provider_id: str) -> ProviderMetrics:
        return self._metrics.setdefault(
            provider_id,
            ProviderMetrics(provider_id=provider_id),
        )

    def all(self) -> list[ProviderMetrics]:
        return list(self._metrics.values())

    @staticmethod
    def _average(current_average: float, count: int, new_value: float) -> float:
        if count <= 1:
            return new_value
        return current_average + ((new_value - current_average) / count)
