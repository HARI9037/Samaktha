"""P10.5 — Communication Manager Boundary Tests.

Proves CommunicationManager accepts but remains disconnected from canonical IntegrationRegistry.
"""

import pytest
import warnings

from app.communication.manager import CommunicationManager
from app.communication.provider import TestProvider
from app.integrations.registry import IntegrationRegistry


def test_communication_manager_accepts_integration_registry():
    """Prove CommunicationManager accepts integration_registry without breaking."""
    integ_registry = IntegrationRegistry()

    # It should accept the registry but default to None if not provided
    mgr_no_reg = CommunicationManager()
    assert mgr_no_reg._integration_registry is None

    mgr_with_reg = CommunicationManager(integration_registry=integ_registry)
    assert mgr_with_reg._integration_registry is integ_registry


def test_test_provider_is_deprecated():
    """Prove TestProvider raises a deprecation warning."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")

        provider = TestProvider()

        assert len(w) >= 1
        assert issubclass(w[-1].category, DeprecationWarning)
        assert "TestProvider is deprecated" in str(w[-1].message)
