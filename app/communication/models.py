"""Phase 15 — Communication models.

Deterministic models for all communication actions.
No provider logic, no credentials, no secrets.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CommunicationProvider(str, Enum):
    SMTP = "smtp"
    GMAIL = "gmail"
    OUTLOOK = "outlook"
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    SLACK = "slack"
    SMS = "sms"
    WEBHOOK = "webhook"
    PUSH = "push"
    DESKTOP = "desktop"


class CommunicationPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class CommunicationStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CommunicationRequest(BaseModel):
    """Deterministic communication request model."""

    sender: str = Field(description="Sender identifier")
    recipient: str = Field(description="Recipient identifier")
    provider: CommunicationProvider = Field(description="Communication provider")
    subject: str = Field(default="", description="Message subject")
    body: str = Field(default="", description="Message body")
    attachments: list[str] = Field(default_factory=list, description="Attachment file paths")
    priority: CommunicationPriority = Field(default=CommunicationPriority.NORMAL)
    approval_required: bool = Field(default=True, description="Whether CAP approval is required")
    metadata: dict[str, Any] = Field(default_factory=dict)


class CommunicationResult(BaseModel):
    """Deterministic communication result model."""

    status: CommunicationStatus
    provider: CommunicationProvider
    message_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    delivery_status: str = "unknown"
    errors: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CommunicationHistoryEntry(BaseModel):
    """Deterministic delivery history entry."""

    recipient: str
    provider: CommunicationProvider
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: CommunicationStatus
    subject: str = ""
    message_id: str | None = None
    errors: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AttachmentMetadata(BaseModel):
    """Metadata for a communication attachment."""

    filename: str
    mime_type: str
    size_bytes: int
    sha256: str = ""
    safe_filename: str = ""
    duplicate: bool = False


class CommunicationDiagnostics(BaseModel):
    """Communication subsystem diagnostics."""

    registered_providers: list[str] = Field(default_factory=list)
    provider_health: dict[str, bool] = Field(default_factory=dict)
    missing_credentials: list[str] = Field(default_factory=list)
    attachment_support: dict[str, bool] = Field(default_factory=dict)
    notification_backend: str = "desktop"
    permission_mappings: dict[str, list[str]] = Field(default_factory=dict)
    total_messages_sent: int = 0
    total_errors: int = 0