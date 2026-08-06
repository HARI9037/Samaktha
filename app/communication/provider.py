"""Phase 15 — Communication provider interfaces.

ABC for all communication providers.
No secrets, no credentials, no user authentication.
Only interfaces.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from app.communication.models import CommunicationRequest, CommunicationResult


class CommunicationProvider(ABC):
    """Abstract base class for all communication providers."""

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection to the provider."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the provider."""

    @abstractmethod
    async def send(self, request: CommunicationRequest) -> CommunicationResult:
        """Send a communication request."""

    @abstractmethod
    async def receive(self, limit: int = 10) -> list[CommunicationResult]:
        """Receive communication results."""

    @abstractmethod
    async def health(self) -> bool:
        """Check provider health."""

    @abstractmethod
    async def validate(self, request: CommunicationRequest) -> list[str]:
        """Validate a communication request. Returns list of errors."""


class SMTPProvider(CommunicationProvider):
    """SMTP email provider interface."""

    async def connect(self) -> bool:
        return False

    async def disconnect(self) -> None:
        pass

    async def send(self, request: CommunicationRequest) -> CommunicationResult:
        return CommunicationResult(
            status="pending",
            provider="smtp",
            delivery_status="not_configured",
            errors=["SMTP provider not configured"],
        )

    async def receive(self, limit: int = 10) -> list[CommunicationResult]:
        return []

    async def health(self) -> bool:
        return False

    async def validate(self, request: CommunicationRequest) -> list[str]:
        errors = []
        if not request.recipient:
            errors.append("Recipient is required")
        if not request.body and not request.attachments:
            errors.append("Body or attachments are required")
        return errors


class GmailProvider(CommunicationProvider):
    """Gmail email provider interface."""

    async def connect(self) -> bool:
        return False

    async def disconnect(self) -> None:
        pass

    async def send(self, request: CommunicationRequest) -> CommunicationResult:
        return CommunicationResult(
            status="pending",
            provider="gmail",
            delivery_status="not_configured",
            errors=["Gmail provider not configured"],
        )

    async def receive(self, limit: int = 10) -> list[CommunicationResult]:
        return []

    async def health(self) -> bool:
        return False

    async def validate(self, request: CommunicationRequest) -> list[str]:
        errors = []
        if not request.recipient:
            errors.append("Recipient is required")
        return errors


class OutlookProvider(CommunicationProvider):
    """Microsoft Outlook email provider interface."""

    async def connect(self) -> bool:
        return False

    async def disconnect(self) -> None:
        pass

    async def send(self, request: CommunicationRequest) -> CommunicationResult:
        return CommunicationResult(
            status="pending",
            provider="outlook",
            delivery_status="not_configured",
            errors=["Outlook provider not configured"],
        )

    async def receive(self, limit: int = 10) -> list[CommunicationResult]:
        return []

    async def health(self) -> bool:
        return False

    async def validate(self, request: CommunicationRequest) -> list[str]:
        errors = []
        if not request.recipient:
            errors.append("Recipient is required")
        return errors


class WhatsAppProvider(CommunicationProvider):
    """WhatsApp messaging provider interface."""

    async def connect(self) -> bool:
        return False

    async def disconnect(self) -> None:
        pass

    async def send(self, request: CommunicationRequest) -> CommunicationResult:
        return CommunicationResult(
            status="pending",
            provider="whatsapp",
            delivery_status="not_configured",
            errors=["WhatsApp provider not configured"],
        )

    async def receive(self, limit: int = 10) -> list[CommunicationResult]:
        return []

    async def health(self) -> bool:
        return False

    async def validate(self, request: CommunicationRequest) -> list[str]:
        errors = []
        if not request.recipient:
            errors.append("Recipient is required")
        return errors


class TelegramProvider(CommunicationProvider):
    """Telegram messaging provider interface."""

    async def connect(self) -> bool:
        return False

    async def disconnect(self) -> None:
        pass

    async def send(self, request: CommunicationRequest) -> CommunicationResult:
        return CommunicationResult(
            status="pending",
            provider="telegram",
            delivery_status="not_configured",
            errors=["Telegram provider not configured"],
        )

    async def receive(self, limit: int = 10) -> list[CommunicationResult]:
        return []

    async def health(self) -> bool:
        return False

    async def validate(self, request: CommunicationRequest) -> list[str]:
        errors = []
        if not request.recipient:
            errors.append("Recipient is required")
        return errors


class DiscordProvider(CommunicationProvider):
    """Discord messaging provider interface."""

    async def connect(self) -> bool:
        return False

    async def disconnect(self) -> None:
        pass

    async def send(self, request: CommunicationRequest) -> CommunicationResult:
        return CommunicationResult(
            status="pending",
            provider="discord",
            delivery_status="not_configured",
            errors=["Discord provider not configured"],
        )

    async def receive(self, limit: int = 10) -> list[CommunicationResult]:
        return []

    async def health(self) -> bool:
        return False

    async def validate(self, request: CommunicationRequest) -> list[str]:
        errors = []
        if not request.recipient:
            errors.append("Recipient is required")
        return errors


class SlackProvider(CommunicationProvider):
    """Slack messaging provider interface."""

    async def connect(self) -> bool:
        return False

    async def disconnect(self) -> None:
        pass

    async def send(self, request: CommunicationRequest) -> CommunicationResult:
        return CommunicationResult(
            status="pending",
            provider="slack",
            delivery_status="not_configured",
            errors=["Slack provider not configured"],
        )

    async def receive(self, limit: int = 10) -> list[CommunicationResult]:
        return []

    async def health(self) -> bool:
        return False

    async def validate(self, request: CommunicationRequest) -> list[str]:
        errors = []
        if not request.recipient:
            errors.append("Recipient is required")
        return errors


class SMSProvider(CommunicationProvider):
    """SMS provider interface."""

    async def connect(self) -> bool:
        return False

    async def disconnect(self) -> None:
        pass

    async def send(self, request: CommunicationRequest) -> CommunicationResult:
        return CommunicationResult(
            status="pending",
            provider="sms",
            delivery_status="not_configured",
            errors=["SMS provider not configured"],
        )

    async def receive(self, limit: int = 10) -> list[CommunicationResult]:
        return []

    async def health(self) -> bool:
        return False

    async def validate(self, request: CommunicationRequest) -> list[str]:
        errors = []
        if not request.recipient:
            errors.append("Recipient is required")
        return errors


class WebhookProvider(CommunicationProvider):
    """Generic HTTP webhook provider interface."""

    async def connect(self) -> bool:
        return False

    async def disconnect(self) -> None:
        pass

    async def send(self, request: CommunicationRequest) -> CommunicationResult:
        return CommunicationResult(
            status="pending",
            provider="webhook",
            delivery_status="not_configured",
            errors=["Webhook provider not configured"],
        )

    async def receive(self, limit: int = 10) -> list[CommunicationResult]:
        return []

    async def health(self) -> bool:
        return False

    async def validate(self, request: CommunicationRequest) -> list[str]:
        errors = []
        if not request.recipient:
            errors.append("Recipient is required")
        return errors


class PushProvider(CommunicationProvider):
    """Push notification provider interface."""

    async def connect(self) -> bool:
        return False

    async def disconnect(self) -> None:
        pass

    async def send(self, request: CommunicationRequest) -> CommunicationResult:
        return CommunicationResult(
            status="pending",
            provider="push",
            delivery_status="not_configured",
            errors=["Push provider not configured"],
        )

    async def receive(self, limit: int = 10) -> list[CommunicationResult]:
        return []

    async def health(self) -> bool:
        return False

    async def validate(self, request: CommunicationRequest) -> list[str]:
        errors = []
        if not request.recipient:
            errors.append("Recipient is required")
        return errors


class DesktopProvider(CommunicationProvider):
    """Desktop notification provider interface."""

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        pass

    async def send(self, request: CommunicationRequest) -> CommunicationResult:
        return CommunicationResult(
            status="sent",
            provider="desktop",
            delivery_status="delivered",
            message_id=f"desktop-{request.recipient}",
        )

    async def receive(self, limit: int = 10) -> list[CommunicationResult]:
        return []

    async def health(self) -> bool:
        return True

    async def validate(self, request: CommunicationRequest) -> list[str]:
        errors = []
        if not request.recipient:
            errors.append("Recipient is required")
        return errors