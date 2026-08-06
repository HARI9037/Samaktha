"""Phase 15 — Communication formatter.

Formats communication content for providers.
Formatter never sends - it only formats.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from app.communication.models import CommunicationRequest

log = logging.getLogger(__name__)


class CommunicationFormatter:
    """Formats communication content for providers."""

    def format_request(self, request: CommunicationRequest) -> dict:
        """Format a communication request for the provider."""
        return {
            "sender": request.sender,
            "recipient": request.recipient,
            "provider": request.provider.value,
            "subject": self._sanitize_subject(request.subject),
            "body": self._sanitize_body(request.body),
            "attachments": request.attachments,
            "priority": request.priority.value,
            "metadata": request.metadata,
        }

    def format_result(self, result) -> dict:
        """Format a communication result for logging."""
        return {
            "status": result.status.value,
            "provider": result.provider.value,
            "message_id": result.message_id,
            "timestamp": result.timestamp.isoformat() if result.timestamp else None,
            "delivery_status": result.delivery_status,
            "errors": result.errors,
            "metadata": result.metadata,
        }

    def _sanitize_subject(self, subject: str) -> str:
        subject = subject.strip()
        if len(subject) > 200:
            subject = subject[:200]
        return subject

    def _sanitize_body(self, body: str) -> str:
        body = body.strip()
        return body

    def format_history_entry(self, entry) -> dict:
        """Format a history entry for display."""
        return {
            "recipient": entry.recipient,
            "provider": entry.provider.value,
            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
            "status": entry.status.value,
            "subject": entry.subject,
            "message_id": entry.message_id,
            "errors": entry.errors,
        }

    def format_diagnostics(self, diagnostics) -> dict:
        """Format diagnostics for display."""
        return {
            "registered_providers": diagnostics.registered_providers,
            "provider_health": diagnostics.provider_health,
            "missing_credentials": diagnostics.missing_credentials,
            "attachment_support": diagnostics.attachment_support,
            "notification_backend": diagnostics.notification_backend,
            "permission_mappings": diagnostics.permission_mappings,
            "total_messages_sent": diagnostics.total_messages_sent,
            "total_errors": diagnostics.total_errors,
        }