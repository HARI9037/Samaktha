"""P10.3 — Email Productionization Tests."""

import pytest

from app.communication.email_tool import EmailTool
from app.integrations.email_smtp import SMTPIntegrationProvider
from app.integrations.contracts import IntegrationProvider, IntegrationRequest, IntegrationResult, IntegrationStatus
from app.tools.models import CapabilityAvailability


class MockFailingIntegrationProvider(IntegrationProvider):
    """A mock provider that always fails."""

    async def connect(self) -> bool: return True
    async def disconnect(self) -> None: pass
    async def health(self) -> bool: return True
    async def validate(self, request: IntegrationRequest) -> list[str]: return []

    async def execute(self, request: IntegrationRequest) -> IntegrationResult:
        return IntegrationResult(
            status=IntegrationStatus.FAILED,
            provider_id="mock",
            delivery_status="failed",
            errors=["Mock failure"],
        )


@pytest.mark.asyncio
async def test_email_tool_simulated_fallback():
    """Prove that EmailTool without provider defaults to simulated."""
    tool = EmailTool(integration_provider=None)
    result = await tool.run({
        "action": "send",
        "to": ["test@example.com"],
        "subject": "Test",
        "body": "Hello"
    })

    assert result.ok is True
    assert result.data["status"] == "simulated"
    assert result.data["externally_delivered"] is False


@pytest.mark.asyncio
async def test_email_tool_real_delivery():
    """Prove that EmailTool correctly routes to provider and sets externally_delivered=True."""
    # We can test this by mocking the provider.
    class MockSuccessIntegrationProvider(IntegrationProvider):
        async def connect(self) -> bool: return True
        async def disconnect(self) -> None: pass
        async def health(self) -> bool: return True
        async def validate(self, request: IntegrationRequest) -> list[str]: return []
        async def execute(self, request: IntegrationRequest) -> IntegrationResult:
            return IntegrationResult(
                status=IntegrationStatus.DELIVERED,
                provider_id="smtp",
                external_id="mock-id",
                delivery_status="sent",
            )

    tool = EmailTool(integration_provider=MockSuccessIntegrationProvider())
    result = await tool.run({
        "action": "send",
        "to": ["test@example.com"],
        "subject": "Test",
        "body": "Hello"
    })

    assert result.ok is True
    assert result.data["status"] == "delivered"
    assert result.data["externally_delivered"] is True
    assert result.data["message_id"] == "mock-id"


@pytest.mark.asyncio
async def test_email_tool_failing_provider():
    """Prove that failing integration bubbles up safely."""
    tool = EmailTool(integration_provider=MockFailingIntegrationProvider())
    result = await tool.run({
        "action": "send",
        "to": ["test@example.com"],
        "subject": "Test",
        "body": "Hello"
    })

    assert result.ok is False
    assert "Email delivery failed" in result.error


@pytest.mark.asyncio
async def test_smtp_integration_provider():
    """Test SMTPIntegrationProvider basic behavior."""
    provider = SMTPIntegrationProvider(config={})
    assert provider.is_configured() is False

    result = await provider.execute(IntegrationRequest(
        provider_id="smtp",
        action="send",
        payload={"to": "test@example.com", "body": "test"}
    ))

    assert result.status == IntegrationStatus.FAILED
    assert result.delivery_status == "not_configured"

    provider_configured = SMTPIntegrationProvider(config={
        "host": "localhost",
        "port": "1025",
        "from_address": "me@me.com"
    })
    assert provider_configured.is_configured() is True

    val_err = await provider_configured.validate(IntegrationRequest(
        provider_id="smtp",
        action="send",
        payload={"to": "", "body": ""}
    ))
    assert len(val_err) == 2
