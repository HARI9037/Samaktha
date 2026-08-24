"""Canonical runtime reliability contracts.

This module classifies failures and decides semantic retries.  It never
dispatches providers or tools; RuntimeEngine remains the execution owner.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Awaitable, Callable

from pydantic import BaseModel, Field


class FailureType(StrEnum):
    TRANSIENT_PROVIDER_FAILURE = "transient_provider_failure"
    RATE_LIMITED = "rate_limited"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    CONNECTION_ERROR = "connection_error"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_FAILURE = "tool_failure"
    TOOL_SECURITY_DENIED = "tool_security_denied"
    INVALID_REQUEST = "invalid_request"
    CONFIGURATION_ERROR = "configuration_error"
    MODEL_UNAVAILABLE = "model_unavailable"
    AUTHORIZATION_DENIED = "authorization_denied"
    PERMIT_INVALID = "permit_invalid"
    PERMIT_EXPIRED = "permit_expired"
    CANCELLED = "cancelled"
    EXECUTION_TIMEOUT = "execution_timeout"
    CHECKPOINT_INVALID = "checkpoint_invalid"
    CHECKPOINT_STALE = "checkpoint_stale"
    RECOVERY_FAILED = "recovery_failed"
    UNKNOWN_FAILURE = "unknown_failure"
    # P10 External Integration Failures
    INTEGRATION_NOT_CONFIGURED = "integration_not_configured"
    CREDENTIAL_UNAVAILABLE = "credential_unavailable"
    CREDENTIAL_EXPIRED = "credential_expired"
    PROVIDER_AUTH_FAILED = "provider_auth_failed"
    PROVIDER_REJECTED = "provider_rejected"
    EXTERNAL_RATE_LIMIT = "external_rate_limit"
    EXTERNAL_TIMEOUT = "external_timeout"
    EXTERNAL_SUBMISSION_UNKNOWN = "external_submission_unknown"
    EXTERNAL_RESOURCE_NOT_FOUND = "external_resource_not_found"
    EXTERNAL_CONFLICT = "external_conflict"


class SideEffectClass(StrEnum):
    READ_ONLY = "read_only"
    IDEMPOTENT_MUTATION = "idempotent_mutation"
    NON_IDEMPOTENT_MUTATION = "non_idempotent_mutation"


class OperationOutcome(StrEnum):
    NOT_STARTED = "not_started"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED_BEFORE_EFFECT = "failed_before_effect"
    FAILED_AFTER_EFFECT_UNKNOWN = "failed_after_effect_unknown"
    CANCELLED = "cancelled"
    TIMED_OUT_UNKNOWN = "timed_out_unknown"


_RETRYABLE = frozenset({
    FailureType.TRANSIENT_PROVIDER_FAILURE,
    FailureType.RATE_LIMITED,
    FailureType.PROVIDER_TIMEOUT,
    FailureType.PROVIDER_UNAVAILABLE,
    FailureType.CONNECTION_ERROR,
})


class RetryPolicy(BaseModel):
    """Bounded semantic retry policy used by RuntimeEngine."""

    max_attempts: int = Field(default=2, ge=1, le=10)
    initial_delay_s: float = Field(default=0.1, ge=0, le=60)
    max_delay_s: float = Field(default=2.0, ge=0, le=300)
    backoff_multiplier: float = Field(default=2.0, ge=1, le=10)
    retryable_failure_types: frozenset[FailureType] = _RETRYABLE

    def delay_for_retry(self, retry_number: int) -> float:
        if retry_number <= 0:
            return 0.0
        return min(
            self.initial_delay_s * (self.backoff_multiplier ** (retry_number - 1)),
            self.max_delay_s,
        )

    def allows(
        self,
        failure_type: FailureType,
        *,
        attempt: int,
        side_effect: SideEffectClass,
        outcome: OperationOutcome,
    ) -> bool:
        if attempt >= self.max_attempts or failure_type not in self.retryable_failure_types:
            return False
        if failure_type in {
            FailureType.CANCELLED,
            FailureType.AUTHORIZATION_DENIED,
            FailureType.PERMIT_INVALID,
            FailureType.PERMIT_EXPIRED,
        }:
            return False
        if side_effect == SideEffectClass.NON_IDEMPOTENT_MUTATION:
            return outcome in {OperationOutcome.NOT_STARTED, OperationOutcome.FAILED_BEFORE_EFFECT}
        return True


def classify_failure(error: str | BaseException | None, *, action_type: str = "") -> FailureType:
    """Map existing result/exception text into one stable reliability class."""

    if isinstance(error, BaseException):
        name = type(error).__name__.lower()
        text = f"{name}: {error}".lower()
    else:
        text = str(error or "").lower()
    if "cancel" in text:
        return FailureType.CANCELLED
    if "permit" in text and "expired" in text:
        return FailureType.PERMIT_EXPIRED
    if "permit" in text or "operation digest" in text or "tamper" in text:
        return FailureType.PERMIT_INVALID
    if "authoriz" in text or "permission denied" in text or "governance" in text:
        return FailureType.AUTHORIZATION_DENIED
    if "tool_security_denied" in text or "filesystem access" in text and "denied" in text:
        return FailureType.TOOL_SECURITY_DENIED
    if "rate limit" in text or "rate_limited" in text or "429" in text:
        return FailureType.RATE_LIMITED
    if "model" in text and any(word in text for word in ("not found", "invalid", "unknown", "unavailable")):
        return FailureType.MODEL_UNAVAILABLE
    if any(word in text for word in ("configuration", "not configured", "api key", "credential")):
        return FailureType.CONFIGURATION_ERROR
    if any(word in text for word in ("invalid request", "validation", "bad request", "400")):
        return FailureType.INVALID_REQUEST
    if "timeout" in text or "timed out" in text:
        return FailureType.TOOL_TIMEOUT if action_type == "tool" else FailureType.PROVIDER_TIMEOUT
    if any(word in text for word in ("connection", "dns", "reset", "offline")):
        return FailureType.CONNECTION_ERROR
    if any(word in text for word in ("server_error", "server error", "502", "503", "504")):
        return FailureType.TRANSIENT_PROVIDER_FAILURE
    if "unavailable" in text:
        return FailureType.PROVIDER_UNAVAILABLE
    # P10 External Integration Failures
    if "not configured" in text or "not_configured" in text:
        return FailureType.INTEGRATION_NOT_CONFIGURED
    if "credential" in text and ("unavailable" in text or "missing" in text):
        return FailureType.CREDENTIAL_UNAVAILABLE
    if "credential" in text and "expired" in text:
        return FailureType.CREDENTIAL_EXPIRED
    if "auth" in text and "failed" in text:
        return FailureType.PROVIDER_AUTH_FAILED
    if "rejected" in text or "provider_rejected" in text:
        return FailureType.PROVIDER_REJECTED
    if "rate limit" in text or "rate_limited" in text:
        return FailureType.EXTERNAL_RATE_LIMIT
    if "submission_unknown" in text or "unknown" in text and "submission" in text:
        return FailureType.EXTERNAL_SUBMISSION_UNKNOWN
    if "not found" in text and "external" in text:
        return FailureType.EXTERNAL_RESOURCE_NOT_FOUND
    if "conflict" in text:
        return FailureType.EXTERNAL_CONFLICT
    if action_type == "tool":
        return FailureType.TOOL_FAILURE
    return FailureType.UNKNOWN_FAILURE


Sleeper = Callable[[float], Awaitable[None]]
