"""Multimodal executor for Samaktha Runtime.

Routes multimodal requests (images, audio, documents) through the
ProviderManager boundary.  The executor never touches providers directly —
all calls flow:

    Runtime → MultimodalExecutor → ProviderManager → Provider → Model
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from app.core.contracts.multimodal import (
    MediaType,
    MultimodalRequest,
    MultimodalResponse,
)
from app.core.contracts.provider import ProviderCapability
from app.runtime.multimodal_metrics import MultimodalMetricsCollector

if TYPE_CHECKING:
    from app.core.contracts.runtime import RuntimeContext
    from app.core.contracts.protocols import ProviderManagerLike

# Map from MediaType to the capability that can handle it.
_MEDIA_CAPABILITY_MAP: dict[MediaType, ProviderCapability] = {
    MediaType.IMAGE: ProviderCapability.VISION,
    MediaType.VIDEO: ProviderCapability.VISION,
    MediaType.AUDIO: ProviderCapability.AUDIO,
    MediaType.DOCUMENT: ProviderCapability.TEXT_GENERATION,  # Documents are treated as rich text
}


class MultimodalExecutor:
    """Executes multimodal requests through the ProviderManager.

    Responsibilities:
    - Validate the request has a known media type.
    - Select the appropriate capability.
    - Delegate execution to ProviderManager.
    - Return a normalized MultimodalResponse.
    - Record metrics for every execution.
    """

    def __init__(
        self,
        provider_manager: "ProviderManagerLike",
        metrics: Optional[MultimodalMetricsCollector] = None,
    ) -> None:
        self._provider_manager = provider_manager
        self._metrics = metrics or MultimodalMetricsCollector()

    def get_metrics(self) -> dict:
        return self._metrics.get_snapshot()

    async def execute(
        self,
        request: MultimodalRequest,
        provider_id: str,
        context: Optional["RuntimeContext"] = None,
    ) -> MultimodalResponse:
        """Execute a multimodal request against the named provider.

        Args:
            request: The multimodal request containing media input and instructions.
            provider_id: The provider to route through ProviderManager.
            context: Optional runtime context for trace event injection.

        Returns:
            A normalized MultimodalResponse.

        Raises:
            ValueError: If the media type is unsupported.
            RuntimeError: If the provider does not support the required capability.
        """
        media_type = request.input.media_type
        capability = _MEDIA_CAPABILITY_MAP.get(media_type)
        if capability is None:
            raise ValueError(f"Unsupported media type: {media_type}")

        if context and context.trace:
            context.trace.add_event(
                source="runtime.multimodal",
                event_type="multimodal.execution.started",
                media_type=media_type.value,
                provider_id=provider_id,
            )

        started_at = time.perf_counter()
        error: Optional[str] = None

        try:
            # Build provider-agnostic payload and route through ProviderManager.
            payload = {
                "multimodal": True,
                "media_type": media_type.value,
                "media_source": request.input.source,
                "media_id": request.input.media_id,
                "instructions": request.instructions,
                "metadata": {**request.input.metadata, **request.metadata},
            }

            raw = await self._provider_manager.execute_provider(
                provider_id=provider_id,
                payload=payload,
                required_capabilities=[capability.value],
            )

            content = (
                raw.get("content")
                or raw.get("response")
                or raw.get("text")
                or ""
            )
            detected = raw.get("detected_items", [])
            usage = raw.get("usage", {})
            response = MultimodalResponse(
                content=content,
                detected_items=detected if isinstance(detected, list) else [],
                provider_id=provider_id,
                usage=usage if isinstance(usage, dict) else {},
            )

        except Exception as exc:
            error = str(exc)
            response = MultimodalResponse(
                content="",
                provider_id=provider_id,
            )
        finally:
            latency_ms = (time.perf_counter() - started_at) * 1000

        if context and context.trace:
            context.trace.add_event(
                source="runtime.multimodal",
                event_type="multimodal.execution.completed" if not error else "multimodal.execution.failed",
                media_type=media_type.value,
                provider_id=provider_id,
                duration_ms=latency_ms,
            )

        self._metrics.record(
            media_type=media_type,
            provider_id=provider_id,
            latency_ms=latency_ms,
            failed=error is not None,
        )

        if error:
            raise RuntimeError(f"Multimodal execution failed: {error}")

        return response
