import asyncio
import threading

import pytest

from app.communication.email_tool import EmailTool
from app.integrations.email_smtp import SMTPIntegrationProvider
from app.integrations.contracts import IntegrationRequest


@pytest.mark.parametrize("action", ["read", "search", "list_folders", "reply", "forward"])
async def test_mailbox_actions_are_unavailable(action):
    tool = EmailTool()
    result = await tool.run({"action": action, "message_id": "fictional"})
    assert not result.ok
    assert result.data["status"] == "unavailable"
    assert action not in tool.supported_actions
    assert "folders" not in result.data


async def test_smtp_configuration_without_verification_cannot_send(monkeypatch):
    provider = SMTPIntegrationProvider({"host": "smtp.invalid", "port": 587, "from_address": "sender@example.invalid"})
    assert provider.is_configured() and not provider.is_ready()
    def forbidden(payload):
        raise AssertionError("Unverified setup must not contact SMTP")
    monkeypatch.setattr(provider, "_deliver", forbidden)
    result = await EmailTool(provider).run({"action": "send", "recipient": "to@example.invalid", "body": "hello"})
    assert not result.ok


async def test_attachments_cannot_be_silently_dropped():
    result = await EmailTool().run({"action": "send", "attachments": ["report.txt"]})
    assert not result.ok and "attachments" in result.error


async def test_smtp_submission_runs_off_event_loop(monkeypatch):
    provider = SMTPIntegrationProvider({"host": "smtp.invalid", "port": 587, "from_address": "sender@example.invalid"})
    loop_thread = threading.get_ident()
    def deliver(payload):
        assert threading.get_ident() != loop_thread
        return "isolated-submission"
    monkeypatch.setattr(provider, "_deliver", deliver)
    result = await provider.execute(IntegrationRequest(provider_id="smtp", action="send", payload={"to": "to@example.invalid", "body": "hi"}))
    assert result.status.value == "provider_accepted"
    assert result.delivery_status == "unknown"


@pytest.mark.parametrize("use_ssl", [False, True])
@pytest.mark.parametrize("authenticate_only", [False, True])
def test_smtp_verifies_certificates_and_preserves_envelope_recipients(monkeypatch, use_ssl, authenticate_only):
    import ssl
    from unittest.mock import MagicMock
    server = MagicMock()
    server.sendmail.return_value = {}
    constructor = MagicMock(return_value=server)
    monkeypatch.setattr("smtplib.SMTP_SSL" if use_ssl else "smtplib.SMTP", constructor)
    provider = SMTPIntegrationProvider({"host": "smtp.example.invalid", "port": 465 if use_ssl else 587,
        "from_address": "sender@example.invalid", "use_ssl": use_ssl, "use_tls": not use_ssl,
        "username": "sender@example.invalid", "password": "fake-only"})
    if authenticate_only:
        assert provider._authentication_diagnostics_sync()["authentication"]
        server.sendmail.assert_not_called()
    else:
        provider._deliver({"to": ["one@example.invalid", "two@example.invalid"], "body": "test"})
        assert server.sendmail.call_args.args[1] == ["one@example.invalid", "two@example.invalid"]
    context = (constructor.call_args.kwargs if use_ssl else server.starttls.call_args.kwargs)["context"]
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    server.quit.assert_called_once()


def test_smtp_certificate_failure_cannot_verify_authentication(monkeypatch):
    import ssl
    from unittest.mock import MagicMock
    server = MagicMock()
    server.starttls.side_effect = ssl.SSLCertVerificationError("test invalid certificate")
    monkeypatch.setattr("smtplib.SMTP", MagicMock(return_value=server))
    provider = SMTPIntegrationProvider({"host": "smtp.example.invalid", "port": 587,
        "from_address": "sender@example.invalid", "username": "sender@example.invalid", "password": "fake-only"})
    result = provider._authentication_diagnostics_sync()
    assert not result["authentication"] and result["failure_stage"] == "tls"
    server.login.assert_not_called()
    server.sendmail.assert_not_called()
