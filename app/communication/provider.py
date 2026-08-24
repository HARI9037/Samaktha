"""Phase 15 — Communication provider interfaces.

ABC for all communication providers.
No secrets, no credentials, no user authentication.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator

from app.communication.config import CommunicationConfig, validate_smtp_config
from app.communication.models import (
    CommunicationProvider as CommunicationProviderEnum,
)
from app.communication.models import (
    CommunicationRequest,
    CommunicationResult,
    CommunicationStatus,
)

log = logging.getLogger(__name__)


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
    """SMTP email provider with real SMTP delivery.

    Requires a configured ``CommunicationConfig``. Without one every operation
    returns a deterministic ``not_configured`` result and never touches the
    network.
    """

    def __init__(self, config: CommunicationConfig | None = None) -> None:
        self._config = config
        self._message_seq = 0

    def get_config(self) -> CommunicationConfig | None:
        return self._config

    def is_configured(self) -> bool:
        return not validate_smtp_config(self._config)

    async def connect(self) -> bool:
        return self.is_configured()

    async def disconnect(self) -> None:
        pass

    async def send(self, request: CommunicationRequest) -> CommunicationResult:
        config_errors = validate_smtp_config(self._config)
        if config_errors:
            return CommunicationResult(
                status=CommunicationStatus.FAILED,
                provider=CommunicationProviderEnum.SMTP,
                delivery_status="not_configured",
                errors=config_errors,
            )
        validation_errors = await self.validate(request)
        if validation_errors:
            return CommunicationResult(
                status=CommunicationStatus.FAILED,
                provider=CommunicationProviderEnum.SMTP,
                delivery_status="failed",
                errors=validation_errors,
            )
        try:
            message_id = self._deliver(request)
            return CommunicationResult(
                status=CommunicationStatus.SENT,
                provider=CommunicationProviderEnum.SMTP,
                message_id=message_id,
                delivery_status="sent",
                metadata={"from_address": self._config.from_address},
            )
        except Exception as exc:
            log.error("SMTP send failed: %s", exc)
            return CommunicationResult(
                status=CommunicationStatus.FAILED,
                provider=CommunicationProviderEnum.SMTP,
                delivery_status="failed",
                errors=[f"SMTP delivery error: {exc}"],
            )

    def _deliver(self, request: CommunicationRequest) -> str:
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["From"] = self._config.from_address
        msg["To"] = request.recipient
        msg["Subject"] = request.subject or "(no subject)"
        msg.set_content(request.body or "")
        self._message_seq += 1
        message_id = f"smtp-{self._message_seq}"

        if self._config.use_ssl:
            server = smtplib.SMTP_SSL(
                self._config.host, self._config.port, timeout=self._config.timeout_s
            )
        else:
            server = smtplib.SMTP(
                self._config.host, self._config.port, timeout=self._config.timeout_s
            )
        try:
            if self._config.use_tls and not self._config.use_ssl:
                server.starttls()
            if self._config.username:
                server.login(self._config.username, self._config.password)
            failures = server.sendmail(
                self._config.from_address, [request.recipient], msg.as_string()
            )
            if failures:
                raise RuntimeError(f"SMTP rejected recipients: {sorted(failures)}")
        finally:
            try:
                server.quit()
            except Exception:
                pass
        return message_id

    async def receive(self, limit: int = 10) -> list[CommunicationResult]:
        return []

    async def health(self) -> bool:
        return self.is_configured()

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


class TestProvider(CommunicationProvider):
    """Deterministic in-memory provider for tests and offline operation.

    Records every sent message so tests can assert on delivery without any
    external dependency. Health is always true once connected.

    DEPRECATED in P10: Use IntegrationRegistry and TestIntegrationProvider instead.
    """

    __test__ = False

    def __init__(self) -> None:
        import warnings
        warnings.warn(
            "TestProvider is deprecated. Use TestIntegrationProvider.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._sent: list[CommunicationResult] = []
        self._seq = 0

    @property
    def sent_messages(self) -> list[CommunicationResult]:
        return list(self._sent)

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        pass

    async def send(self, request: CommunicationRequest) -> CommunicationResult:
        validation_errors = await self.validate(request)
        if validation_errors:
            return CommunicationResult(
                status=CommunicationStatus.FAILED,
                provider=CommunicationProviderEnum.TEST,
                delivery_status="failed",
                errors=validation_errors,
            )
        self._seq += 1
        result = CommunicationResult(
            status=CommunicationStatus.SENT,
            provider=CommunicationProviderEnum.TEST,
            message_id=f"test-{self._seq}",
            delivery_status="delivered",
            metadata={"recipient": request.recipient, "subject": request.subject},
        )
        self._sent.append(result)
        return result

    async def receive(self, limit: int = 10) -> list[CommunicationResult]:
        return self._sent[-limit:]

    async def health(self) -> bool:
        return True

    async def validate(self, request: CommunicationRequest) -> list[str]:
        errors = []
        if not request.recipient:
            errors.append("Recipient is required")
        if not request.body and not request.attachments:
            errors.append("Body or attachments are required")
        return errors
