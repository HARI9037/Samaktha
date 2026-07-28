import time
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Optional

from app.core.contracts.streaming import StreamChunk, StreamEventType, StreamRequest

from app.providers.base import BaseProvider
from app.providers.config import ProviderSettings
from app.providers.metrics import ProviderMetrics, ProviderMetricsStore
from app.providers.health import ProviderHealthChecker, ProviderStatus
from app.providers.models import ProviderInfo, ProviderResponse
from app.providers.registry import ProviderRegistry
from app.providers.selector import ProviderSelectionEngine


class ProviderManager:
    """Coordinates access to the ProviderRegistry."""

    def __init__(
        self,
        registry: ProviderRegistry,
        settings: Optional[ProviderSettings] = None,
        health_checker: Optional[ProviderHealthChecker] = None,
        selection_engine: Optional[ProviderSelectionEngine] = None,
    ) -> None:
        self._registry = registry
        self._settings = settings or ProviderSettings()
        self._health_checker = health_checker or ProviderHealthChecker(settings)
        self._selection_engine = selection_engine or ProviderSelectionEngine(
            registry=registry,
            health_checker=self._health_checker,
        )
        self._cooldowns: dict[str, datetime] = {}
        self._metrics = ProviderMetricsStore()

    def resolve_provider(self, provider_id: str) -> Optional[BaseProvider]:
        """Resolve a provider from the registry."""
        return self._registry.get_provider(provider_id)

    def list_providers(self) -> list:
        """List all available providers."""
        return self._registry.list_providers()

    async def stream_provider(
        self,
        request: StreamRequest,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a response incrementally from the provider.
        
        Validates the provider exists and supports the required capabilities,
        then forwards the StreamRequest to the underlying provider.
        """
        provider_id = request.provider_id
        selected = self._registry.get_info(provider_id)
        if selected is None:
            raise ValueError(f"Provider '{provider_id}' is not registered.")
            
        if not self.get_provider_status(provider_id).available:
            raise RuntimeError(f"Provider '{provider_id}' is currently unavailable.")

        # Empty capabilities implies unconstrained (legacy). 
        # If strict capabilities are provided, validate them.
        if selected.capabilities and request.capabilities:
            missing = set(request.capabilities) - set(selected.capabilities)
            if missing:
                raise ValueError(f"Provider '{provider_id}' missing capabilities: {missing}")

        provider = self._registry.get_provider(provider_id)
        if provider is None:
            raise ValueError(f"Provider '{provider_id}' instance not found.")

        stream_id = f"stream-{request.request_id}"
        yield StreamChunk(
            stream_id=stream_id,
            event_type=StreamEventType.STARTED,
            content="",
            timestamp=time.time(),
            sequence_number=1,
        )
        stream_payload = {
            "prompt": request.prompt,
            "model_id": request.metadata.get("model_id") or self._default_model(selected),
        }
        sequence_number = 2
        async for token in provider.execute_stream(stream_payload):
            yield StreamChunk(
                stream_id=stream_id,
                event_type=StreamEventType.TOKEN,
                content=token,
                timestamp=time.time(),
                sequence_number=sequence_number,
            )
            sequence_number += 1
        yield StreamChunk(
            stream_id=stream_id,
            event_type=StreamEventType.COMPLETED,
            content="",
            timestamp=time.time(),
            sequence_number=sequence_number,
        )

    def get_provider_status(self, provider_id: str) -> ProviderStatus:
        """Inspect provider health using local configuration only."""
        status = self._health_checker.check(
            provider_id=provider_id,
            provider=self._registry.get_provider(provider_id),
        )
        if self._is_in_cooldown(provider_id):
            status.available = False
            status.rate_limited = True
            status.last_error = "Provider is temporarily unavailable"
        return status

    def list_provider_status(self) -> list[ProviderStatus]:
        """List health status for all registered providers."""
        return [
            self.get_provider_status(info.provider_id)
            for info in self._registry.list_providers()
        ]

    def list_available_providers(self) -> list[ProviderStatus]:
        """List registered providers that are enabled and configured."""
        return [
            status
            for status in self.list_provider_status()
            if status.available
        ]

    def list_unavailable_providers(self) -> list[ProviderStatus]:
        """List registered providers that are disabled or missing configuration."""
        return [
            status
            for status in self.list_provider_status()
            if not status.available
        ]

    def select_provider(
        self,
        required_capabilities: list[str],
        preferred_provider: str | None = None,
        preferred_model: str | None = None,
    ) -> Optional[ProviderInfo]:
        """Select a provider through the deterministic selection engine."""
        return self._selection_engine.select_provider(
            required_capabilities=required_capabilities,
            preferred_provider=preferred_provider,
            preferred_model=preferred_model,
        )

    async def execute_provider(
        self,
        provider_id: str,
        payload: dict[str, Any],
        model_id: str | None = None,
        required_capabilities: list[str] | None = None,
    ) -> dict[str, Any]:
        """Execute a provider with deterministic fallback and metrics."""
        attempted: set[str] = set()
        selected = self._registry.get_info(provider_id)
        if selected is None:
            return ProviderResponse(
                success=False,
                message=f"Provider is not registered: {provider_id}",
                provider_id=provider_id,
                model_id=model_id or "",
                finish_reason="unavailable",
            ).model_dump()

        candidates = [selected]
        if self._settings.fallback_enabled:
            candidates.extend(
                provider
                for provider in self._registry.list_providers()
                if provider.provider_id != provider_id
            )

        required = required_capabilities or list(selected.capabilities)
        final_response: ProviderResponse | None = None
        for candidate in candidates:
            if candidate.provider_id in attempted:
                continue
            attempted.add(candidate.provider_id)
            # Empty capability metadata is legacy/unconstrained registration
            # data. Preserve execution for providers registered that way.
            if candidate.capabilities and not set(required).issubset(
                set(candidate.capabilities)
            ):
                continue
            if not self.get_provider_status(candidate.provider_id).available:
                final_response = self._unavailable_response(candidate, model_id)
                self._metrics.record(candidate.provider_id, final_response)
                continue

            context_error = self._validate_context(candidate, payload, model_id)
            if context_error is not None:
                self._metrics.record(candidate.provider_id, context_error)
                return context_error.model_dump()

            provider = self._registry.get_provider(candidate.provider_id)
            if provider is None:
                continue
            response: ProviderResponse | None = None
            retry_limit = max(0, self._settings.max_retries)
            for attempt in range(retry_limit + 1):
                raw = await provider.execute({
                    **payload,
                    "model_id": model_id or self._default_model(candidate),
                })
                response = self._normalize_response(raw, candidate.provider_id, model_id)
                transient = response.finish_reason in {
                    "rate_limited", "server_error", "timeout", "unavailable"
                }
                if response.success or not transient or attempt >= retry_limit:
                    break
            response = response or self._unavailable_response(candidate, model_id)
            self._metrics.record(candidate.provider_id, response)
            if response.finish_reason in {"rate_limited", "server_error", "timeout", "unavailable"}:
                self._mark_cooldown(candidate.provider_id)
            if response.success:
                return response.model_dump()
            final_response = response
            if not self._settings.fallback_enabled:
                break

        return (
            final_response
            or ProviderResponse(
                success=False,
                message="No compatible provider is available",
                provider_id=provider_id,
                model_id=model_id or "",
                finish_reason="unavailable",
            )
        ).model_dump()

    async def execute_provider_stream(
        self,
        provider_id: str,
        payload: dict[str, Any],
        model_id: str | None = None,
        required_capabilities: list[str] | None = None,
    ):
        selected = self._registry.get_info(provider_id)
        if selected is None:
            return
        required = required_capabilities or list(selected.capabilities)
        candidates = [selected]
        if self._settings.fallback_enabled:
            candidates.extend(
                info for info in self._registry.list_providers()
                if info.provider_id != provider_id
            )
        for candidate in candidates:
            if not set(required).issubset(set(candidate.capabilities)):
                continue
            if not self.get_provider_status(candidate.provider_id).available:
                continue
            context_error = self._validate_context(candidate, payload, model_id)
            if context_error is not None:
                return
            provider = self._registry.get_provider(candidate.provider_id)
            if provider is None:
                continue
            stream_payload = {
                **payload,
                "model_id": model_id or self._default_model(candidate),
            }
            try:
                async for chunk in provider.execute_stream(stream_payload):
                    yield chunk
                return
            except Exception:
                self._mark_cooldown(candidate.provider_id)
                if not self._settings.fallback_enabled:
                    return

    def get_provider_metrics(self, provider_id: str) -> ProviderMetrics:
        return self._metrics.get(provider_id)

    def list_provider_metrics(self) -> list[ProviderMetrics]:
        return self._metrics.all()

    def _normalize_response(
        self,
        raw: dict[str, Any],
        provider_id: str,
        model_id: str | None,
    ) -> ProviderResponse:
        if "response" in raw and "content" not in raw:
            raw = {
                "success": True,
                "content": raw["response"],
                "provider_id": provider_id,
                "model_id": model_id or self._default_model(self._registry.get_info(provider_id)),
                "metadata": {"legacy_response": raw},
            }
        return ProviderResponse(
            success=bool(raw.get("success", True)),
            message=raw.get("message"),
            content=raw.get("content", ""),
            provider_id=raw.get("provider_id") or provider_id,
            model_id=raw.get("model_id") or model_id or "",
            finish_reason=raw.get("finish_reason"),
            usage=raw.get("usage") or {},
            cost=raw.get("cost") or {},
            latency_ms=raw.get("latency_ms"),
            metadata=raw.get("metadata") or {},
        )

    def _validate_context(
        self,
        provider: ProviderInfo,
        payload: dict[str, Any],
        model_id: str | None,
    ) -> ProviderResponse | None:
        maximum_context = int(provider.metadata.get("maximum_context", 0) or 0)
        if maximum_context <= 0:
            return None
        prompt = str(payload.get("prompt", ""))
        estimated_tokens = max(1, len(prompt) // 4) if prompt else 0
        requested_output = int(payload.get("max_tokens") or self._settings.max_output_tokens)
        if estimated_tokens + requested_output <= maximum_context:
            return None
        return ProviderResponse(
            success=False,
            message="Context window exceeded",
            provider_id=provider.provider_id,
            model_id=model_id or self._default_model(provider),
            finish_reason="context_window_exceeded",
            metadata={
                "estimated_context_tokens": estimated_tokens,
                "maximum_context": maximum_context,
                "requested_output_tokens": requested_output,
            },
        )

    def _unavailable_response(
        self,
        provider: ProviderInfo,
        model_id: str | None,
    ) -> ProviderResponse:
        return ProviderResponse(
            success=False,
            message=f"Provider unavailable: {provider.provider_id}",
            provider_id=provider.provider_id,
            model_id=model_id or self._default_model(provider),
            finish_reason="unavailable",
        )

    def _mark_cooldown(self, provider_id: str) -> None:
        self._cooldowns[provider_id] = datetime.now(timezone.utc) + timedelta(
            seconds=self._settings.cooldown_seconds,
        )

    def _is_in_cooldown(self, provider_id: str) -> bool:
        until = self._cooldowns.get(provider_id)
        if until is None:
            return False
        if until <= datetime.now(timezone.utc):
            self._cooldowns.pop(provider_id, None)
            return False
        return True

    @staticmethod
    def _default_model(provider: ProviderInfo | None) -> str:
        if provider is None:
            return ""
        models = provider.supported_models or provider.models
        return models[0] if models else ""
