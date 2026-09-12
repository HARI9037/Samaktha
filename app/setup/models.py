from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, SecretStr, field_validator


class SetupCapabilityState(StrEnum):
    AVAILABLE = "available"
    CONFIGURED = "configured"
    VERIFIED = "verified"
    DISABLED = "disabled"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    EXPERIMENTAL = "experimental"


class ValidationStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    DISABLED = "disabled"
    EXPERIMENTAL = "experimental"


class ValidationResult(BaseModel):
    validator_id: str
    label: str
    status: ValidationStatus
    detail: str = ""
    critical: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityReadiness(BaseModel):
    capability_id: str
    implemented: bool
    configured: bool
    verified: bool
    enabled: bool
    state: SetupCapabilityState
    experimental: bool = False
    reason: str = ""


class SetupDraft(BaseModel):
    """Transactional wizard input. SecretStr values are never serialized."""

    display_name: str = ""
    workspace_path: str
    memory_enabled: bool = True
    session_history_enabled: bool = True
    primary_provider: str = "groq"
    provider_model: str = ""
    provider_endpoint: str = ""
    provider_api_key: SecretStr | None = Field(default=None, exclude=True)
    provider_credential_state: str = "no_secret_configured"
    remove_provider_credential: bool = False
    provider_verified: bool = False
    import_environment_credential: bool = False
    search_enabled: bool = True
    search_provider: str = "ddgs"
    searxng_url: str = ""
    brave_api_key: SecretStr | None = Field(default=None, exclude=True)
    brave_credential_state: str = "no_secret_configured"
    remove_brave_credential: bool = False
    search_verified: bool = False
    shell_enabled: bool = False
    smtp_enabled: bool = False
    smtp_preset: str = "custom"
    smtp_sender: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_security: str = "starttls"
    smtp_username: str = ""
    smtp_password: SecretStr | None = Field(default=None, exclude=True)
    smtp_credential_state: str = "no_secret_configured"
    remove_smtp_credential: bool = False
    smtp_auth_verified: bool = False
    notifications_enabled: bool = False
    ocr_enabled: bool = False
    voice_enabled: bool = False
    developer_plugins_enabled: bool = False
    offline_without_provider: bool = False

    @field_validator("primary_provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"groq", "openai", "openrouter", "local", "later"}:
            raise ValueError("Unsupported AI provider selection.")
        return normalized

    @field_validator("search_provider")
    @classmethod
    def validate_search(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"ddgs", "searxng", "brave"}:
            raise ValueError("Unsupported search provider selection.")
        return normalized

    @field_validator("smtp_security")
    @classmethod
    def validate_smtp_security(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"starttls", "ssl"}:
            raise ValueError("SMTP security must be STARTTLS or SSL/TLS.")
        return normalized


class SetupOutcome(BaseModel):
    completed: bool
    ready: bool
    validations: list[ValidationResult] = Field(default_factory=list)
    capabilities: list[CapabilityReadiness] = Field(default_factory=list)
