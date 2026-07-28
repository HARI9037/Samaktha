import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.contracts.provider import ProviderCapability
from app.providers.base import BaseProvider
from app.providers.config import ProviderSettings
from app.providers.models import ProviderResponse
from app.providers.usage import UsageTracker


class LocalProvider(BaseProvider):
    """Provider implementation for Local inference servers (e.g., Ollama)."""

    def __init__(self, settings: ProviderSettings) -> None:
        self._settings = settings
        self._usage_tracker = UsageTracker()

    @property
    def name(self) -> str:
        return "local"

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_timestamp = datetime.now(timezone.utc)
        started = time.perf_counter()
        if not self._settings.local_base_url:
            response = ProviderResponse(
                success=False,
                message="Local provider unavailable: missing base URL",
                provider_id=self.name,
                model_id=self._settings.local_model or "unknown",
                finish_reason="missing_configuration",
                latency_ms=(time.perf_counter() - started) * 1000,
            )
            return response.model_dump()

        model_id = payload.get("model") or payload.get("model_id") or self._settings.local_model or "local-default"
        try:
            async with httpx.AsyncClient(timeout=self._settings.request_timeout_seconds) as client:
                response = await client.post(
                    f"{self._settings.local_base_url.rstrip('/')}/api/generate",
                    json={
                        "model": model_id,
                        "prompt": payload.get("prompt", ""),
                        "stream": False,
                        "options": {
                            "num_predict": payload.get(
                                "max_tokens", self._settings.max_output_tokens
                            )
                        },
                    },
                )
            if response.status_code == 429:
                return self._response(
                    success=False,
                    message="Local provider rate limited",
                    content="",
                    model_id=model_id,
                    request_timestamp=request_timestamp,
                    started=started,
                    finish_reason="rate_limited",
                    metadata={"status_code": 429},
                ).model_dump()
            if response.status_code >= 500:
                return self._response(
                    success=False,
                    message=f"Local provider server error: HTTP {response.status_code}",
                    content="",
                    model_id=model_id,
                    request_timestamp=request_timestamp,
                    started=started,
                    finish_reason="server_error",
                    metadata={"status_code": response.status_code},
                ).model_dump()
            response.raise_for_status()
            data = response.json()
            return self._response(
                success=True,
                message=None,
                content=data.get("response") or data.get("content") or "",
                model_id=model_id,
                request_timestamp=request_timestamp,
                started=started,
                finish_reason="stop" if data.get("done", True) else None,
                prompt_tokens=int(data.get("prompt_eval_count", 0) or 0),
                completion_tokens=int(data.get("eval_count", 0) or 0),
            ).model_dump()
        except httpx.TimeoutException:
            return self._response(
                success=False,
                message="Local provider timeout",
                content="",
                model_id=model_id,
                request_timestamp=request_timestamp,
                started=started,
                finish_reason="timeout",
            ).model_dump()
        except httpx.HTTPError as exc:
            return self._response(
                success=False,
                message=f"Local provider unavailable: {exc}",
                content="",
                model_id=model_id,
                request_timestamp=request_timestamp,
                started=started,
                finish_reason="unavailable",
            ).model_dump()

    async def execute_stream(self, payload: dict[str, Any]):
        response = await self.execute(payload)
        content = response.get("content", "")
        if content:
            yield content

    def _response(
        self,
        success: bool,
        message: str | None,
        content: str,
        model_id: str,
        request_timestamp: datetime,
        started: float,
        finish_reason: str | None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        metadata: dict | None = None,
    ) -> ProviderResponse:
        response_timestamp = datetime.now(timezone.utc)
        usage = self._usage_tracker.track(
            provider=self.name,
            model=model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            request_timestamp=request_timestamp,
            response_timestamp=response_timestamp,
        ).model_dump()
        return ProviderResponse(
            success=success,
            message=message,
            content=content,
            provider_id=self.name,
            model_id=model_id,
            finish_reason=finish_reason,
            usage=usage if self._settings.usage_enabled else {},
            cost={"input_cost": 0.0, "output_cost": 0.0, "total_cost": 0.0, "currency": "USD"}
            if self._settings.cost_enabled
            else {},
            latency_ms=(time.perf_counter() - started) * 1000,
            metadata=metadata or {},
        )

    def supports(self, capability: ProviderCapability) -> bool:
        return capability == ProviderCapability.TEXT_GENERATION

    async def health_check(self) -> bool:
        if not self._settings.local_base_url:
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(self._settings.local_base_url)
                return response.status_code == 200
        except Exception:
            return False
