"""Resolve setup configuration into existing runtime contracts."""

from __future__ import annotations

import os
from typing import Any

from app.config.credentials import CredentialStore, production_credential_store
from app.config.store import SettingsStore
from app.providers.config import ProviderSettings


PROVIDER_CREDENTIAL_IDS = {
    "groq": "samaktha.provider.groq.api_key",
    "openai": "samaktha.provider.openai.api_key",
    "openrouter": "samaktha.provider.openrouter.api_key",
    "brave": "samaktha.search.brave.api_key",
}
SMTP_PASSWORD_CREDENTIAL_ID = "samaktha.email.smtp.password"


def resolve_provider_settings(
    *, settings_store: SettingsStore | None = None,
    credential_store: CredentialStore | None = None,
    base: ProviderSettings | None = None,
) -> ProviderSettings:
    """Resolve env/.env first, then persistent setup, then safe defaults."""
    base = base or ProviderSettings()
    store = settings_store or SettingsStore()
    if not store.exists():
        return base
    providers = store.load().get("providers", {})
    values = base.model_dump()
    explicit = set(base.model_fields_set)
    mapping: dict[str, Any] = {
        "default_provider": providers.get("primary", "groq"),
        "groq_enabled": providers.get("groq", {}).get("enabled", False),
        "groq_model": providers.get("groq", {}).get("model", values["groq_model"]),
        "openai_enabled": providers.get("openai", {}).get("enabled", False),
        "openai_model": providers.get("openai", {}).get("model", values["openai_model"]),
        "openrouter_enabled": providers.get("openrouter", {}).get("enabled", False),
        "openrouter_model": providers.get("openrouter", {}).get("model", values["openrouter_model"]),
        "local_enabled": providers.get("local", {}).get("enabled", False),
        "local_base_url": providers.get("local", {}).get("endpoint") or None,
        "local_model": providers.get("local", {}).get("model") or None,
    }
    for field, value in mapping.items():
        if field not in explicit:
            values[field] = value
    references = {
        "groq_api_key": providers.get("groq", {}).get("credential_id", ""),
        "openai_api_key": providers.get("openai", {}).get("credential_id", ""),
        "openrouter_api_key": providers.get("openrouter", {}).get("credential_id", ""),
    }
    needed = {field: ref for field, ref in references.items() if ref and field not in explicit}
    if needed:
        secure = credential_store or production_credential_store()
        for field, reference in needed.items():
            values[field] = secure.get(str(reference))
    return ProviderSettings(**values)


def resolve_smtp_credentials(
    *, settings_store: SettingsStore | None = None,
    credential_store: CredentialStore | None = None,
) -> dict[str, Any]:
    """Resolve SMTP env compatibility before secure persistent setup."""
    environment = {
        "host": os.getenv("SMTP_HOST"), "port": os.getenv("SMTP_PORT"),
        "username": os.getenv("SMTP_USERNAME"), "password": os.getenv("SMTP_PASSWORD"),
        "from_address": os.getenv("SMTP_FROM"),
        "use_tls": os.getenv("SMTP_USE_TLS", "true").lower() == "true",
        "use_ssl": os.getenv("SMTP_USE_SSL", "false").lower() == "true",
    }
    if environment["host"] or environment["from_address"]:
        return environment
    store = settings_store or SettingsStore()
    if not store.exists():
        return environment
    email = store.load().get("email", {})
    if not email.get("smtp_enabled", False):
        return environment
    reference = str(email.get("password_credential_id", ""))
    password = None
    if reference:
        password = (credential_store or production_credential_store()).get(reference)
    security = str(email.get("security", "starttls")).lower()
    return {
        "host": email.get("host"), "port": email.get("port"),
        "username": email.get("username"), "password": password,
        "from_address": email.get("sender"),
        "smtp_enabled": bool(email.get("smtp_enabled")),
        "auth_verified": bool(email.get("auth_verified")),
        "use_tls": security == "starttls",
        "use_ssl": security in {"ssl", "ssl_tls"},
    }


def resolve_brave_api_key(*, settings_store: SettingsStore | None = None, credential_store: CredentialStore | None = None) -> str:
    """Resolve environment compatibility before the secure setup reference."""
    environment = os.getenv("SAMAKTHA_BRAVE_API_KEY", "")
    if environment:
        return environment
    store = settings_store or SettingsStore()
    if not store.exists():
        return ""
    reference = str(store.load().get("search", {}).get("brave_credential_id", ""))
    if not reference:
        return ""
    return (credential_store or production_credential_store()).get(reference) or ""
