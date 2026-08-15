"""P1.6 — Communication retry policy.

A small deterministic retry policy used by ``CommunicationManager`` for
outbound delivery. Retries only transient (failed) outcomes up to
``max_attempts`` with an optional fixed backoff.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet

from app.communication.models import CommunicationStatus

DEFAULT_RETRYABLE_STATUSES = frozenset({CommunicationStatus.FAILED})


@dataclass(frozen=True)
class RetryPolicy:
    """Policy governing outbound delivery retries."""

    max_attempts: int = 3
    backoff_s: float = 0.0
    retryable_statuses: FrozenSet[CommunicationStatus] = field(
        default_factory=lambda: DEFAULT_RETRYABLE_STATUSES
    )

    def is_retryable(self, status: CommunicationStatus) -> bool:
        return status in self.retryable_statuses

    def attempts(self) -> int:
        return max(1, self.max_attempts)

    def backoff(self) -> float:
        return max(0.0, self.backoff_s)
