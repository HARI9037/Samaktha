"""Phase 15 — Communication policy.

Defines communication policy rules for CAP governance.
"""

from __future__ import annotations

from app.communication.models import CommunicationProvider, CommunicationPriority


COMMUNICATION_PERMISSIONS = {
    CommunicationProvider.SMTP: ["network", "email"],
    CommunicationProvider.GMAIL: ["network", "email"],
    CommunicationProvider.OUTLOOK: ["network", "email"],
    CommunicationProvider.WHATSAPP: ["network", "messaging"],
    CommunicationProvider.TELEGRAM: ["network", "messaging"],
    CommunicationProvider.DISCORD: ["network", "messaging"],
    CommunicationProvider.SLACK: ["network", "messaging"],
    CommunicationProvider.SMS: ["network", "sms"],
    CommunicationProvider.WEBHOOK: ["network", "webhook"],
    CommunicationProvider.PUSH: ["network", "push"],
    CommunicationProvider.DESKTOP: ["local", "notification"],
}


COMMUNICATION_RISK = {
    CommunicationProvider.SMTP: "HIGH",
    CommunicationProvider.GMAIL: "HIGH",
    CommunicationProvider.OUTLOOK: "HIGH",
    CommunicationProvider.WHATSAPP: "HIGH",
    CommunicationProvider.TELEGRAM: "HIGH",
    CommunicationProvider.DISCORD: "MEDIUM",
    CommunicationProvider.SLACK: "MEDIUM",
    CommunicationProvider.SMS: "HIGH",
    CommunicationProvider.WEBHOOK: "HIGH",
    CommunicationProvider.PUSH: "MEDIUM",
    CommunicationProvider.DESKTOP: "LOW",
}


def get_required_permissions(provider: CommunicationProvider) -> list[str]:
    return COMMUNICATION_PERMISSIONS.get(provider, [])


def get_risk_level(provider: CommunicationProvider) -> str:
    return COMMUNICATION_RISK.get(provider, "UNKNOWN")


def requires_approval(provider: CommunicationProvider) -> bool:
    return provider != CommunicationProvider.DESKTOP