"""P10.2 — Canonical External Integration Contracts.

Tests that the new Integration boundaries are sound.
"""

import pytest

from app.integrations.contracts import (
    IntegrationRequest,
    IntegrationResult,
    IntegrationStatus,
)
from app.integrations.registry import IntegrationRegistry
from app.integrations.adapters import TestIntegrationProvider


def test_integration_result_ok_property():
    """Prove ok property accurately reflects DELIVERED or SIMULATED states."""
    delivered = IntegrationResult(status=IntegrationStatus.DELIVERED, provider_id="test")
    assert delivered.ok is True

    simulated = IntegrationResult(status=IntegrationStatus.SIMULATED, provider_id="test")
    assert simulated.ok is True

    failed = IntegrationResult(status=IntegrationStatus.FAILED, provider_id="test")
    assert failed.ok is False

    pending = IntegrationResult(status=IntegrationStatus.PENDING, provider_id="test")
    assert pending.ok is False


@pytest.mark.asyncio
async def test_test_integration_provider():
    """Prove TestIntegrationProvider follows the contract."""
    provider = TestIntegrationProvider("test_provider")

    assert await provider.health() is False
    await provider.connect()
    assert await provider.health() is True

    req = IntegrationRequest(
        provider_id="test_provider",
        action="test_action",
        payload={"foo": "bar"}
    )

    result = await provider.execute(req)
    assert result.status == IntegrationStatus.DELIVERED
    assert result.ok is True
    assert result.external_id == "test-1"
    assert len(provider.sent) == 1

    # Bad provider id
    bad_req = IntegrationRequest(
        provider_id="wrong_provider",
        action="test_action",
        payload={}
    )
    bad_result = await provider.execute(bad_req)
    assert bad_result.status == IntegrationStatus.FAILED
    assert bad_result.ok is False
    assert "Provider mismatch" in bad_result.errors[0]

    await provider.disconnect()
    assert await provider.health() is False


def test_integration_registry():
    """Prove IntegrationRegistry manages providers correctly."""
    registry = IntegrationRegistry()
    provider = TestIntegrationProvider("test_provider")

    registry.register("test_provider", provider)

    assert registry.get("test_provider") is provider
    assert "test_provider" in registry.list_providers()

    with pytest.raises(ValueError):
        registry.register("test_provider", provider)

    assert registry.unregister("test_provider") is True
    assert registry.get("test_provider") is None
