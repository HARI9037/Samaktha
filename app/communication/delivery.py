"""Phase 15 — Communication delivery tracking.

Tracks delivery status of communication messages.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.communication.models import CommunicationResult, CommunicationStatus

log = logging.getLogger(__name__)


class DeliveryTracker:
    """Tracks delivery status of communication messages."""

    def __init__(self) -> None:
        self._deliveries: dict[str, CommunicationResult] = {}

    def track(self, result: CommunicationResult) -> None:
        if result.message_id:
            self._deliveries[result.message_id] = result

    def get_status(self, message_id: str) -> CommunicationResult | None:
        return self._deliveries.get(message_id)

    def update_status(self, message_id: str, status: CommunicationStatus) -> bool:
        delivery = self._deliveries.get(message_id)
        if delivery is None:
            return False
        delivery.status = status
        return True

    def list_all(self) -> list[CommunicationResult]:
        return list(self._deliveries.values())

    def list_by_status(self, status: CommunicationStatus) -> list[CommunicationResult]:
        return [d for d in self._deliveries.values() if d.status == status]

    def list_failed(self) -> list[CommunicationResult]:
        return self.list_by_status(CommunicationStatus.FAILED)

    def count(self) -> int:
        return len(self._deliveries)

    def count_by_status(self, status: CommunicationStatus) -> int:
        return len(self.list_by_status(status))


class DeliveryService:
    """Service for managing delivery tracking."""

    def __init__(self) -> None:
        self._tracker = DeliveryTracker()

    async def record_delivery(self, result: CommunicationResult) -> None:
        self._tracker.track(result)

    async def get_delivery_status(self, message_id: str) -> CommunicationResult | None:
        return self._tracker.get_status(message_id)

    async def retry_failed(self) -> list[CommunicationResult]:
        failed = self._tracker.list_failed()
        return failed

    def get_stats(self) -> dict:
        return {
            "total": self._tracker.count(),
            "sent": self._tracker.count_by_status(CommunicationStatus.SENT),
            "delivered": self._tracker.count_by_status(CommunicationStatus.DELIVERED),
            "failed": self._tracker.count_by_status(CommunicationStatus.FAILED),
            "cancelled": self._tracker.count_by_status(CommunicationStatus.CANCELLED),
        }