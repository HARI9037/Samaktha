from __future__ import annotations

import json
from dataclasses import asdict
from unittest.mock import patch

import pytest

from app.communication.email_tool import EmailTool
from app.communication.manager import CommunicationManager
from app.integrations.contracts import (
    ExternalSubmissionStatus,
    IntegrationRequest,
    IntegrationStatus,
)
from app.integrations.email_smtp import SMTPIntegrationProvider


def _provider(secret: str = "P13_SMTP_PASSWORD") -> SMTPIntegrationProvider:
    return SMTPIntegrationProvider({
        "host": "smtp.example.test",
        "port": 587,
        "from_address": "sender@example.test",
        "username": "sender",
        "password": secret,
        "use_tls": True,
        "use_ssl": False,
    })


def _request() -> IntegrationRequest:
    return IntegrationRequest(
        provider_id="smtp",
        action="send",
        payload={
            "to": "recipient@example.test",
            "subject": "P13",
            "body": "safe body",
        },
    )


@pytest.mark.asyncio
async def test_smtp_acceptance_is_not_delivery_confirmation() -> None:
    provider = _provider()
    with patch("smtplib.SMTP") as smtp:
        smtp.return_value.sendmail.return_value = {}
        result = await provider.execute(_request())
    assert result.status is IntegrationStatus.PROVIDER_ACCEPTED
    assert result.submission_status is ExternalSubmissionStatus.PROVIDER_ACCEPTED
    assert result.delivery_status == "unknown"
    assert result.externally_delivered is False


@pytest.mark.asyncio
async def test_smtp_unknown_failure_is_not_success_and_redacts_credentials() -> None:
    secret = "P13_SENTINEL_CREDENTIAL"
    provider = _provider(secret)
    with patch("smtplib.SMTP") as smtp:
        smtp.side_effect = OSError(f"password={secret}")
        result = await provider.execute(_request())
    rendered = json.dumps(asdict(result), default=str)
    assert result.status is IntegrationStatus.FAILED
    assert result.submission_status is ExternalSubmissionStatus.FAILED_AFTER_SUBMISSION_UNKNOWN
    assert secret not in rendered


@pytest.mark.asyncio
async def test_email_tool_preserves_unknown_delivery_truth() -> None:
    tool = EmailTool(integration_provider=_provider())
    with patch("smtplib.SMTP") as smtp:
        smtp.return_value.sendmail.return_value = {}
        result = await tool.run({
            "action": "send",
            "recipient": "recipient@example.test",
            "subject": "P13",
            "body": "safe body",
        })
    assert result.ok
    assert result.data["status"] == "provider_accepted"
    assert result.data["externally_delivered"] is False
    assert result.data["delivery_status"] == "unknown"


def test_communication_manager_remains_outside_production_composition(
    production_orchestrator,
) -> None:
    assert not any(
        isinstance(value, CommunicationManager)
        for value in vars(production_orchestrator).values()
    )


@pytest.mark.asyncio
async def test_message_actions_remain_simulated(production_orchestrator) -> None:
    message = production_orchestrator.tool_registry.get_tool("message")
    result = await message.run({
        "action": "send",
        "recipient": "nobody@example.test",
        "body": "not externally sent",
    })
    assert result.ok
    assert result.data["status"] == "simulated"
    assert result.data["externally_delivered"] is False
