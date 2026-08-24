"""P10 Canonical Integration Subsystem."""

from .contracts import IntegrationProvider, IntegrationRequest, IntegrationResult, IntegrationStatus
from .registry import IntegrationRegistry

__all__ = [
    "IntegrationProvider",
    "IntegrationRequest",
    "IntegrationResult",
    "IntegrationStatus",
    "IntegrationRegistry",
]
