"""Phase 15 — Communication manager.

Manages communication lifecycle through the production runtime.

All outbound communication goes through CAP governance: every request that
marks itself ``approval_required`` must carry an explicit ``approved`` marker
in its metadata (set by the CAP-approved tool flow) before the manager will
dispatch it. This manager only orchestrates; it does not bypass any layer.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.communication.history import CommunicationHistory
from app.communication.models import (
    CommunicationHistoryEntry,
    CommunicationRequest,
    CommunicationResult,
    CommunicationStatus,
)
from app.communication.provider import CommunicationProvider
from app.communication.registry import CommunicationRegistry
from app.communication.retry import RetryPolicy

log = logging.getLogger(__name__)

APPROVAL_MARKER = "approved"
APPROVAL_MISSING_ERROR = "CAP approval required for this outbound communication"


class CommunicationManager:
    """Manages communication through the production runtime pipeline.

    All outbound communication goes through CAP governance.
    This manager only orchestrates; it does not bypass any layer.
    """

    def __init__(
        self,
        registry: CommunicationRegistry | None = None,
        history: CommunicationHistory | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._registry = registry or CommunicationRegistry()
        self._history = history or CommunicationHistory()
        self._retry_policy = retry_policy or RetryPolicy()

    def get_registry(self) -> CommunicationRegistry:
        return self._registry

    def get_history(self) -> CommunicationHistory:
        return self._history

    def get_retry_policy(self) -> RetryPolicy:
        return self._retry_policy

    def _record(self, result: CommunicationResult, request: CommunicationRequest) -> None:
        try:
            self._history.add_entry(
                CommunicationHistoryEntry(
                    recipient=request.recipient,
                    provider=result.provider,
                    timestamp=result.timestamp,
                    status=result.status,
                    subject=request.subject,
                    message_id=result.message_id,
                    errors=result.errors,
                    metadata={"sender": request.sender, "priority": request.priority.value},
                )
            )
        except Exception as exc:  # audit must never break delivery
            log.error("Failed to record communication audit entry: %s", exc)

    async def send(
        self,
        request: CommunicationRequest,
        retry_policy: RetryPolicy | None = None,
    ) -> CommunicationResult:
        """Send a communication request through the provider under CAP.

        Retries transient failures according to the effective retry policy.
        Every outcome is appended to the audit history.
        """
        effective = retry_policy or self._retry_policy

        if request.approval_required and not request.metadata.get(APPROVAL_MARKER):
            result = CommunicationResult(
                status=CommunicationStatus.FAILED,
                provider=request.provider,
                delivery_status="approval_required",
                errors=[APPROVAL_MISSING_ERROR],
            )
            self._record(result, request)
            return result

        provider = self._registry.get_provider(request.provider.value)
        if provider is None:
            result = CommunicationResult(
                status=CommunicationStatus.FAILED,
                provider=request.provider,
                errors=[f"Provider {request.provider.value} not registered"],
            )
            self._record(result, request)
            return result

        validation_errors = await provider.validate(request)
        if validation_errors:
            result = CommunicationResult(
                status=CommunicationStatus.FAILED,
                provider=request.provider,
                errors=validation_errors,
            )
            self._record(result, request)
            return result

        attempts = effective.attempts()
        last_result: CommunicationResult | None = None
        for attempt in range(attempts):
            last_result = await self._send_once(provider, request)
            if not effective.is_retryable(last_result.status):
                break
            if attempt < attempts - 1 and effective.backoff() > 0:
                await asyncio.sleep(effective.backoff())
        result = last_result or CommunicationResult(
            status=CommunicationStatus.FAILED,
            provider=request.provider,
            errors=["No delivery attempt completed"],
        )
        self._record(result, request)
        return result

    async def _send_once(
        self, provider: CommunicationProvider, request: CommunicationRequest
    ) -> CommunicationResult:
        try:
            return await provider.send(request)
        except Exception as exc:
            log.error("Communication send failed: %s", exc)
            return CommunicationResult(
                status=CommunicationStatus.FAILED,
                provider=request.provider,
                errors=[str(exc)],
            )

    def health_check(self) -> dict[str, bool]:
        return self._registry.health_check()

    def list_providers(self) -> list[str]:
        return self._registry.list_providers()

    def has_provider(self, name: str) -> bool:
        return self._registry.has_provider(name)
