from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx

from app.providers.config import ProviderSettings
from app.providers.cost import CostEstimator
from app.providers.models import ProviderResponse
from app.providers.usage import UsageTracker


class OpenAICompatibleChatClient:
    """HTTP client for OpenAI-compatible chat completion APIs."""

    def __init__(
        self,
        provider_id: str,
        api_key: str | None,
        model_id: str,
        base_url: str,
        settings: ProviderSettings,
        default_headers: dict[str, str] | None = None,
        display_name: str | None = None,
    ) -> None:
        self._provider_id = provider_id
        self._api_key = api_key
        self._model_id = model_id
        self._base_url = base_url.rstrip("/")
        self._settings = settings
        self._default_headers = default_headers or {}
        self._display_name = display_name or provider_id.title()
        self._usage_tracker = UsageTracker()
        self._cost_estimator = CostEstimator()

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_timestamp = datetime.now(timezone.utc)
        started = time.perf_counter()
        if not self._api_key:
            return self._response(
                success=False,
                message=f"{self._display_name} provider unavailable: missing API key",
                content="",
                finish_reason=None,
                request_timestamp=request_timestamp,
                started=started,
            ).model_dump()

        prompt = str(payload.get("prompt", ""))
        model_id = str(payload.get("model") or payload.get("model_id") or self._model_id)
        body = {
            "model": model_id,
            "messages": payload.get("messages") or [{"role": "user", "content": prompt}],
            "stream": False,
        }
        if "max_tokens" in payload:
            body["max_tokens"] = payload["max_tokens"]
        elif self._settings.max_output_tokens:
            body["max_tokens"] = self._settings.max_output_tokens

        try:
            async with httpx.AsyncClient(timeout=self._settings.request_timeout_seconds) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers=self._headers(),
                    json=body,
                )
            if response.status_code == 429:
                return self._rate_limited(request_timestamp, started, model_id).model_dump()
            if response.status_code >= 500:
                return self._response(
                    success=False,
                    message=f"{self._provider_id} provider server error: HTTP {response.status_code}",
                    content="",
                    finish_reason="server_error",
                    request_timestamp=request_timestamp,
                    started=started,
                    model_id=model_id,
                    metadata={"status_code": response.status_code},
                ).model_dump()
            response.raise_for_status()
            data = response.json()
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            usage = data.get("usage") or {}
            return self._response(
                success=True,
                message=None,
                content=message.get("content") or "",
                finish_reason=choice.get("finish_reason"),
                request_timestamp=request_timestamp,
                started=started,
                model_id=model_id,
                prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
                completion_tokens=int(usage.get("completion_tokens", 0) or 0),
                metadata={"raw_provider": self._provider_id},
            ).model_dump()
        except httpx.TimeoutException:
            return self._response(
                success=False,
                message=f"{self._provider_id} provider timeout",
                content="",
                finish_reason="timeout",
                request_timestamp=request_timestamp,
                started=started,
                model_id=model_id,
            ).model_dump()
        except httpx.HTTPStatusError as exc:
            text = exc.response.text.lower()
            finish_reason = "rate_limited" if "quota" in text or "rate" in text else "http_error"
            return self._response(
                success=False,
                message=f"{self._provider_id} provider HTTP error: {exc.response.status_code}",
                content="",
                finish_reason=finish_reason,
                request_timestamp=request_timestamp,
                started=started,
                model_id=model_id,
                metadata={"status_code": exc.response.status_code},
            ).model_dump()
        except httpx.HTTPError as exc:
            return self._response(
                success=False,
                message=f"{self._provider_id} provider unavailable: {exc}",
                content="",
                finish_reason="unavailable",
                request_timestamp=request_timestamp,
                started=started,
                model_id=model_id,
            ).model_dump()

    async def execute_stream(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        if not self._settings.stream_enabled:
            response = await self.execute(payload)
            content = response.get("content", "")
            if content:
                yield content
            return
        if not self._api_key:
            return

        prompt = str(payload.get("prompt", ""))
        model_id = str(payload.get("model") or payload.get("model_id") or self._model_id)
        body = {
            "model": model_id,
            "messages": payload.get("messages") or [{"role": "user", "content": prompt}],
            "stream": True,
        }
        if "max_tokens" in payload:
            body["max_tokens"] = payload["max_tokens"]
        elif self._settings.max_output_tokens:
            body["max_tokens"] = self._settings.max_output_tokens
        async with httpx.AsyncClient(timeout=self._settings.request_timeout_seconds) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                headers=self._headers(),
                json=body,
            ) as response:
                if response.status_code >= 400:
                    error_body = await response.aread()
                    error_text = ""
                    try:
                        error_data = json.loads(error_body)
                        error_text = error_data.get("error", {}).get("message", "") or str(error_data)
                    except (json.JSONDecodeError, AttributeError):
                        error_text = error_body.decode("utf-8", errors="replace")[:500]
                    raise httpx.HTTPStatusError(
                        f"{self._display_name} stream error {response.status_code}: {error_text}",
                        request=response.request,
                        response=response,
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line.removeprefix("data: ").strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    delta = ((chunk.get("choices") or [{}])[0].get("delta") or {})
                    content = delta.get("content")
                    if content:
                        yield content

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            **self._default_headers,
        }

    def _rate_limited(
        self,
        request_timestamp: datetime,
        started: float,
        model_id: str,
    ) -> ProviderResponse:
        return self._response(
            success=False,
            message=f"{self._provider_id} provider rate limited",
            content="",
            finish_reason="rate_limited",
            request_timestamp=request_timestamp,
            started=started,
            model_id=model_id,
            metadata={"status_code": 429},
        )

    def _response(
        self,
        success: bool,
        message: str | None,
        content: str,
        finish_reason: str | None,
        request_timestamp: datetime,
        started: float,
        model_id: str | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        metadata: dict | None = None,
    ) -> ProviderResponse:
        model_id = model_id or self._model_id
        response_timestamp = datetime.now(timezone.utc)
        usage = self._usage_tracker.track(
            provider=self._provider_id,
            model=model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            request_timestamp=request_timestamp,
            response_timestamp=response_timestamp,
        ).model_dump()
        cost = self._cost_estimator.estimate(
            model=model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ).model_dump()
        return ProviderResponse(
            success=success,
            message=message,
            content=content,
            provider_id=self._provider_id,
            model_id=model_id,
            finish_reason=finish_reason,
            usage=usage if self._settings.usage_enabled else {},
            cost=cost if self._settings.cost_enabled else {},
            latency_ms=(time.perf_counter() - started) * 1000,
            metadata=metadata or {},
        )
