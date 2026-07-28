import pytest

from app.core.contracts.provider import ProviderCapability
from app.providers.models import ProviderInfo
from app.providers.registry import ProviderRegistry
from app.providers.mock import MockProvider


@pytest.fixture
def registry():
    return ProviderRegistry()


@pytest.fixture
def mock_provider():
    return MockProvider()


@pytest.fixture
def mock_info():
    return ProviderInfo(
        provider_id="mock",
        capabilities=["text_generation"],
        models=["mock-model"],
        supported_models=["mock-model"],
    )


def test_registry_registration(registry, mock_provider, mock_info):
    registry.register("mock", mock_provider, mock_info)
    assert registry.get_provider("mock") is mock_provider
    assert registry.get_info("mock") is mock_info
    assert "mock" in registry.validate_availability()


def test_registry_removal(registry, mock_provider, mock_info):
    registry.register("mock", mock_provider, mock_info)
    assert registry.remove("mock") is True
    assert registry.get_provider("mock") is None
    assert registry.remove("mock") is False


def test_registry_discovery(registry, mock_provider, mock_info):
    registry.register("mock", mock_provider, mock_info)
    
    # MockProvider supports all capabilities
    found = registry.find_by_capability(ProviderCapability.TEXT_GENERATION)
    assert len(found) == 1
    assert found[0].provider_id == "mock"
