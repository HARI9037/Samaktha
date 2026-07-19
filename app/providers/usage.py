from datetime import datetime, timezone

from pydantic import BaseModel


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    provider: str = ""
    model: str = ""
    request_timestamp: datetime
    response_timestamp: datetime


class UsageTracker:
    """Builds deterministic token usage metadata for provider responses."""

    def track(
        self,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        request_timestamp: datetime,
        response_timestamp: datetime | None = None,
    ) -> TokenUsage:
        response_timestamp = response_timestamp or datetime.now(timezone.utc)
        return TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            provider=provider,
            model=model,
            request_timestamp=request_timestamp,
            response_timestamp=response_timestamp,
        )
