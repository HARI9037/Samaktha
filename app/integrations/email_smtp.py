"""P10.3 — SMTP Integration Provider.

Canonical external integration adapter for SMTP.

SMTP successful message acceptance means:
submission_status = PROVIDER_ACCEPTED
and typically:
delivery_status = DELIVERY_UNKNOWN

unless actual provider status mechanism proves recipient delivery.
"""

from typing import Any

from app.integrations.contracts import (
    IntegrationProvider,
    IntegrationRequest,
    IntegrationResult,
    IntegrationStatus,
    ExternalSubmissionStatus,
)
from app.evidence.sanitizer import sanitize_exception


class SMTPIntegrationProvider(IntegrationProvider):
    """Canonical integration for sending emails via SMTP."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize with bounded config mapping from CredentialResolver."""
        self._config = config or {}
        self._message_seq = 0

    def is_configured(self) -> bool:
        """Check if minimum required credentials are present."""
        return bool(
            self._config.get("host") and
            self._config.get("port") and
            self._config.get("from_address")
        )

    async def connect(self) -> bool:
        return self.is_configured()

    async def disconnect(self) -> None:
        pass

    async def health(self) -> bool:
        return self.is_configured()

    async def validate(self, request: IntegrationRequest) -> list[str]:
        errors = []
        payload = request.payload
        if not payload.get("to"):
            errors.append("Recipient (to) is required")
        if not payload.get("body") and not payload.get("attachments"):
            errors.append("Body or attachments are required")
        return errors

    async def execute(self, request: IntegrationRequest) -> IntegrationResult:
        if not self.is_configured():
            return IntegrationResult(
                status=IntegrationStatus.FAILED,
                provider_id="smtp",
                submission_status=ExternalSubmissionStatus.FAILED_BEFORE_SUBMISSION,
                delivery_status="not_configured",
                errors=["SMTP provider not configured"],
            )

        validation_errors = await self.validate(request)
        if validation_errors:
            return IntegrationResult(
                status=IntegrationStatus.FAILED,
                provider_id="smtp",
                submission_status=ExternalSubmissionStatus.FAILED_BEFORE_SUBMISSION,
                delivery_status="failed",
                errors=validation_errors,
            )

        try:
            message_id = self._deliver(request.payload)
            return IntegrationResult(
                status=IntegrationStatus.PROVIDER_ACCEPTED,
                provider_id="smtp",
                external_id=message_id,
                submission_status=ExternalSubmissionStatus.PROVIDER_ACCEPTED,
                delivery_status="unknown",
                metadata={"from_address": self._config.get("from_address")},
            )
        except Exception as exc:
            safe_error = sanitize_exception(exc)["message"]
            return IntegrationResult(
                status=IntegrationStatus.FAILED,
                provider_id="smtp",
                submission_status=ExternalSubmissionStatus.FAILED_AFTER_SUBMISSION_UNKNOWN,
                delivery_status="failed",
                errors=[f"SMTP delivery error: {safe_error}"],
            )

    def _deliver(self, payload: dict[str, Any]) -> str:
        """Synchronous SMTP delivery (blocking).

        The execution engine or the ToolExecutor is responsible for handling
        network blocking in a thread pool. Here we just execute the protocol.
        """
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["From"] = self._config.get("from_address")

        to = payload.get("to", [])
        if isinstance(to, list):
            to_str = ", ".join(to)
        else:
            to_str = to

        msg["To"] = to_str
        msg["Subject"] = payload.get("subject") or "(no subject)"
        msg.set_content(payload.get("body") or "")

        self._message_seq += 1
        message_id = f"smtp-{self._message_seq}"

        use_ssl = self._config.get("use_ssl", False)
        use_tls = self._config.get("use_tls", True)
        host = self._config.get("host")
        port = int(self._config.get("port") or (465 if use_ssl else 587))
        timeout = 30.0

        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=timeout)
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)

        try:
            if use_tls and not use_ssl:
                server.starttls()
            username = self._config.get("username")
            password = self._config.get("password")
            if username and password:
                server.login(username, password)

            failures = server.sendmail(
                self._config.get("from_address"),
                [to_str] if isinstance(to_str, str) else to_str,
                msg.as_string()
            )
            if failures:
                raise RuntimeError(f"SMTP rejected recipients: {sorted(failures)}")
        finally:
            try:
                server.quit()
            except Exception:
                pass

        return message_id
