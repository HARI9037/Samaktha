import time
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

        Mirrors the ``execute_provider`` fallback policy: the routed provider
        is always tried first, and on failure it is marked for cooldown and
        the next healthy provider is tried. The stream only fails when every
        candidate fails.
        """
        primary_id = request.provider_id
        if self._registry.get_info(primary_id) is None:
            raise ValueError(f"Provider '{primary_id}' is not registered.")

        stream_id = f"stream-{request.request_id}"
        sequence_number = 1
        yield StreamChunk(
            stream_id=stream_id,
            event_type=StreamEventType.STARTED,
            content="",
            timestamp=time.time(),
            sequence_number=sequence_number,
            metadata={"provider_id": primary_id},
        )
        sequence_number += 1

        candidates = self._candidate_infos(primary_id, request.capabilities)
        attempted: set[str] = set()
        last_error: Exception | None = None
        used_provider = primary_id

        for candidate in candidates:
            candidate_id = candidate.provider_id
            if candidate_id in attempted:
                continue
            attempted.add(candidate_id)
            if not self.get_provider_status(candidate_id).available:
                continue
            provider = self._registry.get_provider(candidate_id)
            if provider is None:
                continue

            stream_payload = {
                "model_id": request.metadata.get("model_id") or self._default_model(candidate),
            }
            if request.messages:
                stream_payload["messages"] = request.messages
                stream_payload["prompt"] = request.messages[-1].get("content", "")
            else:
                stream_payload["prompt"] = request.prompt

            used_provider = candidate_id
            try:
                async for token in provider.execute_stream(stream_payload):
                    yield StreamChunk(
                        stream_id=stream_id,
                        event_type=StreamEventType.TOKEN,
                        content=token,
                        timestamp=time.time(),
                        sequence_number=sequence_number,
                        metadata={"provider_id": candidate_id},
                    )
                    sequence_number += 1
                yield StreamChunk(
                    stream_id=stream_id,
                    event_type=StreamEventType.COMPLETED,
                    content="",
                    timestamp=time.time(),
                    sequence_number=sequence_number,
                    metadata={"provider_id": candidate_id},
                )
                return
            except Exception as exc:
                self._mark_cooldown(candidate_id)
                last_error = exc
                if not self._settings.fallback_enabled:
                    break

        if last_error is None:
            raise RuntimeError(
                f"Provider '{primary_id}' is currently unavailable."
            )
        raise RuntimeError(
            f"Provider '{used_provider}' stream failed: {last_error}"
        )

    def _candidate_infos(
        self,
        provider_id: str,
        required_capabilities: list[str] | None,
    ) -> list:
        """Ordered execution candidates for fallback.

        Single source of truth for both the synchronous and streaming
        execution paths: the routed provider first, then the remaining
        registered providers in deterministic registry order. A candidate is
        eligible when it satisfies the required capabilities; empty capability
        metadata is legacy/unconstrained registration data and remains
        executable (mirrors the pre-unification behavior).
        """
        selected = self._registry.get_info(provider_id)
        if selected is None:
            return []
        candidates = [selected]
        if self._settings.fallback_enabled:
            candidates.extend(
                provider
                for provider in self._registry.list_providers()
                if provider.provider_id != provider_id
            )

        required = required_capabilities or list(selected.capabilities)
        return [
            candidate
            for candidate in candidates
            if not candidate.capabilities
            or set(required).issubset(set(candidate.capabilities))
        ]

    def get_provider_status(self, provider_id: str) -> ProviderStatus:
        """Inspect provider health using local configuration only.

        Cooldown is applied by the shared health checker, so providers in
        cooldown are reported unavailable to both selection and execution.
        """
        return self._health_checker.check(
            provider_id=provider_id,
            provider=self._registry.get_provider(provider_id),
        )

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

        candidates = self._candidate_infos(provider_id, required_capabilities)
        final_response: ProviderResponse | None = None
        for candidate in candidates:
            if candidate.provider_id in attempted:
                continue
            attempted.add(candidate.provider_id)
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
                    "rate_limited", "server_error", "timeout", "unavailable", "http_error"
                }
                if response.success or not transient or attempt >= retry_limit:
                    break
            response = response or self._unavailable_response(candidate, model_id)
            self._metrics.record(candidate.provider_id, response)
            if response.finish_reason in {"rate_limited", "server_error", "timeout", "unavailable", "http_error"}:
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
        candidates = self._candidate_infos(provider_id, required_capabilities)
        for candidate in candidates:
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
        self._health_checker.mark_cooldown(provider_id)

    def _is_in_cooldown(self, provider_id: str) -> bool:
        return self._health_checker.is_in_cooldown(provider_id)

    @staticmethod
    def _default_model(provider: ProviderInfo | None) -> str:
        if provider is None:
            return ""
        models = provider.supported_models or provider.models
        return models[0] if models else ""
