"""P1.6 — Communication configuration and SMTP config validation.

``CommunicationConfig`` carries SMTP connection settings (never secrets in
code — only env-loaded values) and ``validate_smtp_config`` returns a
deterministic list of missing/invalid fields.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

SMTP_ENV_PREFIX = "SAMAKTHA_SMTP_"


class CommunicationConfig(BaseModel):
    """SMTP delivery configuration."""

    host: str = Field(default="", description="SMTP server host")
    port: int = Field(default=587, description="SMTP server port")
    username: str = Field(default="", description="SMTP auth username")
    password: str = Field(default="", description="SMTP auth password")
    from_address: str = Field(default="", description="From: address")
    use_tls: bool = Field(default=True, description="StartTLS on connect")
    use_ssl: bool = Field(default=False, description="Implicit TLS (SMTPS)")
    timeout_s: float = Field(default=10.0, description="Socket timeout seconds")


def validate_smtp_config(config: CommunicationConfig | None) -> list[str]:
    """Return configuration errors; empty list means usable for SMTP."""
    if config is None:
        return ["SMTP is not configured"]
    errors: list[str] = []
    if not config.host:
        errors.append("SMTP host is not configured")
    if not config.from_address:
        errors.append("SMTP from address is not configured")
    if config.port not in (25, 465, 587, 2525):
        errors.append(f"Unsupported SMTP port: {config.port}")
    if not (1 <= config.timeout_s <= 120):
        errors.append(f"Invalid SMTP timeout: {config.timeout_s}")
    return errors


def load_smtp_config(values: dict[str, Any] | None = None) -> CommunicationConfig:
    """Build a ``CommunicationConfig`` from a dict of env-style values.

    Values are read from ``values`` (or the process environment) using the
    ``SAMAKTHA_SMTP_*`` prefix. Missing values fall back to empty defaults,
    so an unconfigured environment yields an unusable-but-safe config.
    """
    import os

    source = values if values is not None else os.environ

    def _get(key: str, default: Any = "") -> Any:
        return source.get(f"{SMTP_ENV_PREFIX}{key}", default)

    return CommunicationConfig(
        host=str(_get("HOST")),
        port=int(_get("PORT", 587)),
        username=str(_get("USERNAME")),
        password=str(_get("PASSWORD")),
        from_address=str(_get("FROM")),
        use_tls=str(_get("USE_TLS", "true")).lower() == "true",
        use_ssl=str(_get("USE_SSL", "false")).lower() == "true",
        timeout_s=float(_get("TIMEOUT_S", 10.0)),
    )
