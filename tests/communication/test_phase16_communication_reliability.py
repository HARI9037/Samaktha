"""P1.6 — Communication reliability tests.

Covers SMTP config validation, real SMTP provider behavior (mocked transport),
the deterministic test provider, outbound retry policy, CAP approval gating,
and the durable communication audit trail.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.communication.config import (
    CommunicationConfig,
    validate_smtp_config,
    load_smtp_config,
)
from app.communication.history import CommunicationHistory
from app.communication.manager import APPROVAL_MISSING_ERROR, CommunicationManager
from app.communication.models import (
    CommunicationHistoryEntry,
    CommunicationProvider,
    CommunicationRequest,
    CommunicationResult,
    CommunicationStatus,
)
from app.communication.provider import SMTPProvider, TestProvider
from app.communication.registry import CommunicationRegistry
from app.communication.retry import RetryPolicy


def _request(
    provider: CommunicationProvider = CommunicationProvider.TEST,
    *,
    recipient: str = "user@example.com",
    body: str = "Hello",
    approved: bool = True,
    approval_required: bool = True,
) -> CommunicationRequest:
    return CommunicationRequest(
        sender="system",
        recipient=recipient,
        provider=provider,
        subject="Test",
        body=body,
        approval_required=approval_required,
        metadata={"approved": approved},
    )


class TestSmtpConfigValidation:
    def test_none_config_is_error(self):
        errors = validate_smtp_config(None)
        assert len(errors) == 1
        assert "not configured" in errors[0]

    def test_empty_config_reports_missing_fields(self):
        config = CommunicationConfig()
        errors = validate_smtp_config(config)
        assert any("host" in e for e in errors)
        assert any("from" in e for e in errors)

    def test_valid_config_has_no_errors(self):
        config = CommunicationConfig(
            host="smtp.example.com", port=587, from_address="noreply@example.com"
        )
        assert validate_smtp_config(config) == []

    def test_invalid_port_rejected(self):
        config = CommunicationConfig(host="smtp.example.com", port=1234)
        errors = validate_smtp_config(config)
        assert any("port" in e for e in errors)

    def test_load_smtp_config_from_values(self):
        config = load_smtp_config(
            {
                "SAMAKTHA_SMTP_HOST": "smtp.example.com",
                "SAMAKTHA_SMTP_PORT": "465",
                "SAMAKTHA_SMTP_USE_SSL": "true",
                "SAMAKTHA_SMTP_FROM": "noreply@example.com",
            }
        )
        assert config.host == "smtp.example.com"
        assert config.port == 465
        assert config.use_ssl is True
        assert validate_smtp_config(config) == []


class TestSMTPProvider:
    def test_unconfigured_provider_is_inert(self):
        provider = SMTPProvider()
        assert provider.is_configured() is False
        assert asyncio.run(provider.connect()) is False
        assert asyncio.run(provider.health()) is False
        result = asyncio.run(provider.send(_request(CommunicationProvider.SMTP)))
        assert result.status == CommunicationStatus.FAILED
        assert result.delivery_status == "not_configured"
        assert result.errors

    def test_send_success_with_mocked_transport(self):
        config = CommunicationConfig(
            host="smtp.example.com",
            port=587,
            username="user",
            password="secret",
            from_address="noreply@example.com",
            use_tls=True,
        )
        provider = SMTPProvider(config)
        server_mock = None

        with patch("smtplib.SMTP") as smtp_cls:
            server_mock = smtp_cls.return_value
            server_mock.sendmail.return_value = {}
            result = asyncio.run(provider.send(_request(CommunicationProvider.SMTP)))

        assert result.status == CommunicationStatus.SENT
        assert result.message_id == "smtp-1"
        assert result.delivery_status == "sent"
        assert server_mock.starttls.called
        assert server_mock.login.called
        assert server_mock.quit.called
        assert result.metadata["from_address"] == "noreply@example.com"

    def test_send_ssl_uses_smtp_ssl(self):
        config = CommunicationConfig(
            host="smtp.example.com",
            port=465,
            from_address="noreply@example.com",
            use_ssl=True,
        )
        provider = SMTPProvider(config)
        with patch("smtplib.SMTP_SSL") as smtp_ssl_cls:
            smtp_ssl_cls.return_value.sendmail.return_value = {}
            result = asyncio.run(provider.send(_request(CommunicationProvider.SMTP)))
        assert result.status == CommunicationStatus.SENT
        assert smtp_ssl_cls.called

    def test_send_failure_returns_structured_error(self):
        config = CommunicationConfig(
            host="smtp.example.com", port=587, from_address="noreply@example.com"
        )
        provider = SMTPProvider(config)
        with patch("smtplib.SMTP") as smtp_cls:
            smtp_cls.return_value.sendmail.side_effect = OSError("connection refused")
            result = asyncio.run(provider.send(_request(CommunicationProvider.SMTP)))
        assert result.status == CommunicationStatus.FAILED
        assert result.delivery_status == "failed"
        assert result.errors and "SMTP delivery error" in result.errors[0]

    def test_validate_requires_recipient_and_content(self):
        config = CommunicationConfig(
            host="smtp.example.com", port=587, from_address="noreply@example.com"
        )
        provider = SMTPProvider(config)
        errors = asyncio.run(
            provider.validate(
                _request(CommunicationProvider.SMTP, recipient="", body="")
            )
        )
        assert "Recipient is required" in errors
        assert any("Body or attachments" in e for e in errors)


class TestTestProvider:
    def test_registered_in_registry(self):
        registry = CommunicationRegistry()
        assert registry.has_provider("test")
        assert isinstance(registry.get_provider("test"), TestProvider)

    def test_send_records_message(self):
        provider = TestProvider()
        result = asyncio.run(provider.send(_request()))
        assert result.status == CommunicationStatus.SENT
        assert result.message_id == "test-1"
        assert len(provider.sent_messages) == 1

    def test_health_true(self):
        provider = TestProvider()
        assert asyncio.run(provider.health()) is True


class TestRetryPolicy:
    def test_defaults(self):
        policy = RetryPolicy()
        assert policy.attempts() == 3
        assert policy.is_retryable(CommunicationStatus.FAILED)
        assert not policy.is_retryable(CommunicationStatus.SENT)

    def test_manager_retries_transient_failure(self):
        class FlakyProvider(TestProvider):
            def __init__(self):
                super().__init__()
                self.attempts = 0

            async def send(self, request):
                self.attempts += 1
                if self.attempts < 3:
                    return CommunicationResult(
                        status=CommunicationStatus.FAILED,
                        provider=CommunicationProvider.TEST,
                        errors=["transient"],
                    )
                return await super().send(request)

        registry = CommunicationRegistry()
        flaky = FlakyProvider()
        registry.register("test", flaky)
        manager = CommunicationManager(registry)
        result = asyncio.run(manager.send(_request()))
        assert result.status == CommunicationStatus.SENT
        assert flaky.attempts == 3

    def test_manager_stops_after_max_attempts(self):
        class AlwaysFail(TestProvider):
            def __init__(self):
                super().__init__()
                self.attempts = 0

            async def send(self, request):
                self.attempts += 1
                return CommunicationResult(
                    status=CommunicationStatus.FAILED,
                    provider=CommunicationProvider.TEST,
                    errors=["always fails"],
                )

        registry = CommunicationRegistry()
        flaky = AlwaysFail()
        registry.register("test", flaky)
        manager = CommunicationManager(registry, retry_policy=RetryPolicy(max_attempts=2))
        result = asyncio.run(manager.send(_request()))
        assert result.status == CommunicationStatus.FAILED
        assert flaky.attempts == 2

    def test_success_does_not_retry(self):
        provider = TestProvider()
        registry = CommunicationRegistry()
        registry.register("test", provider)
        manager = CommunicationManager(registry)
        result = asyncio.run(manager.send(_request()))
        assert result.status == CommunicationStatus.SENT
        assert len(provider.sent_messages) == 1


class TestCapApprovalGate:
    def test_send_without_approval_is_rejected(self):
        manager = CommunicationManager()
        result = asyncio.run(manager.send(_request(approved=False)))
        assert result.status == CommunicationStatus.FAILED
        assert APPROVAL_MISSING_ERROR in result.errors
        assert result.delivery_status == "approval_required"

    def test_send_with_approval_succeeds(self):
        manager = CommunicationManager()
        result = asyncio.run(manager.send(_request(approved=True)))
        assert result.status == CommunicationStatus.SENT

    def test_no_gate_when_approval_not_required(self):
        manager = CommunicationManager()
        result = asyncio.run(
            manager.send(_request(approved=False, approval_required=False))
        )
        assert result.status == CommunicationStatus.SENT

    def test_rejected_attempt_is_audited(self):
        history = CommunicationHistory()
        manager = CommunicationManager(history=history)
        asyncio.run(manager.send(_request(approved=False)))
        assert history.count() == 1
        entry = history.get_last_entry()
        assert entry is not None
        assert entry.status == CommunicationStatus.FAILED


def _entry(recipient: str, subject: str = "Test") -> CommunicationHistoryEntry:
    return CommunicationHistoryEntry(
        recipient=recipient,
        provider=CommunicationProvider.TEST,
        status=CommunicationStatus.SENT,
        subject=subject,
        message_id="m1",
        delivery_status="sent",
    )


class TestAuditTrail:
    def test_history_durable_across_instances(self, tmp_path):
        db_path = str(tmp_path / "comm_history.db")
        history = CommunicationHistory(db_path=db_path)
        assert history.durable() is True
        history.add_entry(_entry("a@b.com", "s1"))
        reopened = CommunicationHistory(db_path=db_path)
        assert reopened.count() == 1
        assert reopened.get_last_entry().recipient == "a@b.com"

    def test_manager_records_durable_audit(self, tmp_path):
        db_path = str(tmp_path / "comm_history.db")
        manager = CommunicationManager(history=CommunicationHistory(db_path=db_path))
        asyncio.run(manager.send(_request(approved=True)))
        reopened = CommunicationHistory(db_path=db_path)
        assert reopened.count() == 1
        entry = reopened.get_last_entry()
        assert entry is not None
        assert entry.status == CommunicationStatus.SENT
        assert entry.recipient == "user@example.com"

    def test_history_bounded_by_max_entries(self, tmp_path):
        db_path = str(tmp_path / "comm_history.db")
        history = CommunicationHistory(max_entries=3, db_path=db_path)
        for i in range(5):
            history.add_entry(_entry(f"r{i}@b.com", f"s{i}"))
        assert history.count() == 3
        entries = history.get_entries()
        assert [e.recipient for e in entries] == ["r2@b.com", "r3@b.com", "r4@b.com"]
        reopened = CommunicationHistory(max_entries=3, db_path=db_path)
        assert reopened.count() == 3

    def test_health_check_reports_provider_states(self):
        manager = CommunicationManager()
        health = manager.health_check()
        assert health["test"] is True
        assert health["smtp"] is False
