import pytest

from app.providers.health import ProviderHealthChecker
from app.providers.mock import MockProvider


@pytest.fixture
def health_checker():
    return ProviderHealthChecker()


def test_health_checker_check(health_checker):
    provider = MockProvider()
    status = health_checker.check("mock", provider)

    assert status.provider_id == "mock"
    assert status.enabled is True
    assert status.configured is True
    assert status.available is True
    assert status.reachable is True
    assert status.last_error is None


def test_health_checker_record_success(health_checker):
    health_checker.record_success("mock", 150.5)

    status = health_checker.get_status("mock")
    assert status is not None
    assert status.successful_calls == 1
    assert status.total_latency_ms == 150.5
    assert status.failures == 0
    assert status.average_latency == 150.5
    assert status.reachable is True


def test_health_checker_record_failure(health_checker):
    health_checker.record_failure("mock", "Timeout error")

    status = health_checker.get_status("mock")
    assert status is not None
    assert status.failures == 1
    assert status.last_error == "Timeout error"
    assert status.reachable is False
