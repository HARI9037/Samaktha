"""Phase 15 — Communication diagnostics.

Provides diagnostics for the communication subsystem.
"""

from __future__ import annotations

from app.communication.models import CommunicationDiagnostics
from app.communication.registry import CommunicationRegistry


def run_diagnostics(registry: CommunicationRegistry) -> CommunicationDiagnostics:
    """Run communication subsystem diagnostics."""
    providers = registry.list_providers()
    health = registry.health_check()

    missing_credentials = []
    for name in providers:
        health_status = "healthy" if health.get(name) else "unhealthy"
        if health_status != "healthy":
            missing_credentials.append(name)

    attachment_support = {
        "smtp": True,
        "gmail": True,
        "outlook": True,
        "whatsapp": False,
        "telegram": False,
        "discord": True,
        "slack": True,
        "sms": False,
        "webhook": True,
        "push": False,
        "desktop": False,
    }

    permission_mappings = {
        "smtp": ["network", "email"],
        "gmail": ["network", "email"],
        "outlook": ["network", "email"],
        "whatsapp": ["network", "messaging"],
        "telegram": ["network", "messaging"],
        "discord": ["network", "messaging"],
        "slack": ["network", "messaging"],
        "sms": ["network", "sms"],
        "webhook": ["network", "webhook"],
        "push": ["network", "push"],
        "desktop": ["local", "notification"],
    }

    total_sent = 0
    total_errors = 0

    return CommunicationDiagnostics(
        registered_providers=providers,
        provider_health=health,
        missing_credentials=missing_credentials,
        attachment_support=attachment_support,
        notification_backend="desktop",
        permission_mappings=permission_mappings,
        total_messages_sent=total_sent,
        total_errors=total_errors,
    )