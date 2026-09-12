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
        """Resolve environment compatibility or secure setup credentials."""
        from app.config.runtime_config import resolve_smtp_credentials

        return resolve_smtp_credentials()
