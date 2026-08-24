"""P10.2 — Integration Failures."""

class IntegrationError(Exception):
    """Base exception for all integration failures."""
    pass


class ConfigurationError(IntegrationError):
    """Raised when an integration is improperly configured."""
    pass


class DeliveryError(IntegrationError):
    """Raised when an external effect fails to deliver."""
    pass
