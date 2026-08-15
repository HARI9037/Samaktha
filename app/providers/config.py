from typing import Optional

import os

from pydantic_settings import BaseSettings, SettingsConfigDict

#: Providers that are allowed in a production composition. Test-only
#: providers (mock) are deliberately absent from this set.
_PRODUCTION_PROVIDERS = ("openai", "groq", "openrouter", "local")


class ProviderStartupError(RuntimeError):
    """Raised when provider configuration prevents production execution.

    Provider credentials are optional at composition time so ``create_app``
    and ``/health`` remain available without keys. Missing configuration
    surfaces as a clean execution-time error instead of a startup failure.
    The message is written to be shown to the user verbatim.
    """


class ProviderSettings(BaseSettings):
    """Configuration for AI intelligence providers."""

    model_config = SettingsConfigDict(
        env_prefix="SAMAKTHA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    default_provider: str = "groq"
    openai_enabled: bool = True
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"
    groq_enabled: bool = True
    groq_api_key: Optional[str] = None
    groq_model: str = "llama-3.3-70b-versatile"
    openrouter_enabled: bool = True
    openrouter_api_key: Optional[str] = None
    openrouter_model: str = "openai/gpt-oss-120b"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    local_enabled: bool = True
    local_base_url: Optional[str] = None
    local_model: Optional[str] = None
    #: MockProvider is test/development only. It is never registered in a
    #: production composition unless ``mock_agent`` or ``dev_mode`` is true.
    mock_enabled: bool = True
    mock_agent: bool = False
    dev_mode: bool = False
    request_timeout_seconds: float = 30.0
    max_retries: int = 0
    cooldown_seconds: int = 60
    stream_enabled: bool = True
    cost_enabled: bool = True
    usage_enabled: bool = True
    fallback_enabled: bool = True
    default_model: str = ""
    max_output_tokens: int = 1024

    # NOTE: There is intentionally NO model_post_init downgrade. Provider
    # availability is enforced by the orchestrator's execution-time gate
    # (see ``_ensure_provider_available``), not at application construction.

    def is_provider_enabled(self, provider_id: str) -> bool:
        """True when the provider's enable flag is set."""
        return bool(getattr(self, f"{provider_id}_enabled", False))

    def is_provider_configured(self, provider_id: str) -> bool:
        """True when the provider has the credentials/base-URL required."""
        return bool(
            {
                "openai": self.openai_api_key,
                "groq": self.groq_api_key,
                "openrouter": self.openrouter_api_key,
                "local": self.local_base_url,
                "mock": True,
            }.get(provider_id)
        )

    def mock_allowed(self) -> bool:
        """Whether the development mock provider may be composed in.

        Mock is allowed only for explicit development mode, MOCK_AGENT, or a
        SAMAKTHA_DEV_MODE environment override. ``mock_enabled`` alone is
        never sufficient for production. This is the single source of truth
        used by both the production composition and startup diagnostics.
        """
        if not self.mock_enabled:
            return False
        if self.mock_agent or self.dev_mode:
            return True
        return os.environ.get("MOCK_AGENT", "").strip().lower() in {
            "1", "true", "yes",
        }

    def configured_production_providers(self) -> list[str]:
        """Registered providers that are enabled and have credentials."""
        return [
            provider_id
            for provider_id in _PRODUCTION_PROVIDERS
            if self.is_provider_enabled(provider_id)
            and self.is_provider_configured(provider_id)
        ]

    def validate_startup(self) -> None:
        """Validate the default provider for production service.

        Raises ``ProviderStartupError`` when the default provider cannot
        serve production. Never silently switches providers. Retained as an
        explicit diagnostic; application construction no longer calls it
        automatically so unconfigured installs remain reachable.
        """
        if not self.default_provider:
            raise ProviderStartupError("No production provider is configured.")

        provider_id = self.default_provider
        if provider_id == "mock":
            if not self.mock_allowed():
                raise ProviderStartupError(
                    "Provider Startup Error\n"
                    "Mock provider is not available in production.\n"
                    "Configure a real provider in .env before starting Samaktha."
                )
            return

        if not self.is_provider_enabled(provider_id):
            raise ProviderStartupError(
                f"Provider Startup Error\n"
                f"{provider_id.capitalize()} is disabled.\n"
                "Configure .env before starting Samaktha."
            )
        if not self.is_provider_configured(provider_id):
            raise ProviderStartupError(
                f"Provider Startup Error\n"
                f"{provider_id.capitalize()} API key missing.\n"
                "Configure .env before starting Samaktha."
            )

    def validate_production(self) -> None:
        """Ensure at least one real provider exists outside dev mode.

        Never silently includes the mock provider. Used by the orchestrator's
        execution-time gate and directly tested; application construction
        does not depend on it.
        """
        if self.configured_production_providers() or self.mock_allowed():
            return
        raise ProviderStartupError(
            "No production provider is configured.\n"
            "Configure .env before starting Samaktha."
        )
