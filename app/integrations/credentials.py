"""P10.2 — Credential Resolution."""

import os
from typing import Optional


class CredentialResolver:
    """Bounded credential resolution for integrations.

    For P10, this resolves from the environment, proving that we do not
    take credentials from the canonical tool execution arguments.
    """

    @staticmethod
    def get_smtp_credentials() -> dict[str, Optional[str]]:
        """Resolve SMTP credentials from the environment."""
        return {
            "host": os.getenv("SMTP_HOST"),
            "port": os.getenv("SMTP_PORT"),
            "username": os.getenv("SMTP_USERNAME"),
            "password": os.getenv("SMTP_PASSWORD"),
            "from_address": os.getenv("SMTP_FROM"),
            "use_tls": os.getenv("SMTP_USE_TLS", "true").lower() == "true",
            "use_ssl": os.getenv("SMTP_USE_SSL", "false").lower() == "true",
        }
