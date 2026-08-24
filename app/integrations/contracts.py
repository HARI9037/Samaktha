"""P10.2 — Canonical External Integration Contracts.

Defines the universal boundary for all external integrations in Samaktha.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IntegrationStatus(str, Enum):
    """Execution status for an external integration request."""
    PENDING = "pending"
    PROVIDER_ACCEPTED = "provider_accepted"
    DELIVERED = "delivered"
    FAILED = "failed"
    SIMULATED = "simulated"


class ExternalSubmissionStatus(str, Enum):
    """Detailed submission status for external effects.

    SMTP successful message acceptance means:
    submission_status = PROVIDER_ACCEPTED
    and typically:
    delivery_status = DELIVERY_UNKNOWN

    unless actual provider status mechanism proves recipient delivery.
    """
    DRAFTED = "drafted"
    NOT_SUBMITTED = "not_submitted"
    SUBMISSION_STARTED = "submission_started"
    PROVIDER_ACCEPTED = "provider_accepted"
    PROVIDER_REJECTED = "provider_rejected"
    DELIVERY_CONFIRMED = "delivery_confirmed"
    DELIVERY_UNKNOWN = "delivery_unknown"
    FAILED_BEFORE_SUBMISSION = "failed_before_submission"
    FAILED_AFTER_SUBMISSION_UNKNOWN = "failed_after_submission_unknown"
    CANCELLED = "cancelled"


@dataclass
class IntegrationRequest:
    """Canonical request crossing the integration boundary."""
    provider_id: str
    action: str
    payload: dict[str, Any]


@dataclass
class IntegrationResult:
    """Canonical result from an external integration."""
    status: IntegrationStatus
    provider_id: str
    external_id: str | None = None
    submission_status: ExternalSubmissionStatus = ExternalSubmissionStatus.DELIVERY_UNKNOWN
    delivery_status: str = "pending"
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in (IntegrationStatus.DELIVERED, IntegrationStatus.PROVIDER_ACCEPTED, IntegrationStatus.SIMULATED)

    @property
    def externally_delivered(self) -> bool:
        """True only when delivery is confirmed, not merely provider-accepted."""
        return self.status == IntegrationStatus.DELIVERED and self.submission_status == ExternalSubmissionStatus.DELIVERY_CONFIRMED


class IntegrationProvider(ABC):
    """Base class for all real external providers (Email, Calendar, Contacts, etc)."""

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection or verify configuration."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Tear down connection."""
        pass

    @abstractmethod
    async def health(self) -> bool:
        """Check provider health/readiness."""
        pass

    @abstractmethod
    async def validate(self, request: IntegrationRequest) -> list[str]:
        """Validate the request before execution."""
        pass

    @abstractmethod
    async def execute(self, request: IntegrationRequest) -> IntegrationResult:
        """Execute the external effect."""
        pass

    def is_configured(self) -> bool:
        """Check if provider has minimum required configuration.

        Defaults to True for test providers. Real providers (SMTP, etc.)
        should override to check actual configuration.
        """
        return True
