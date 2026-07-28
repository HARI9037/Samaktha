from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    mock_enabled: bool = True
    request_timeout_seconds: float = 30.0
    max_retries: int = 0
    cooldown_seconds: int = 60
    stream_enabled: bool = True
    cost_enabled: bool = True
    usage_enabled: bool = True
    fallback_enabled: bool = True
    default_model: str = "mock-model"
    max_output_tokens: int = 1024

    def model_post_init(self, __context) -> None:
        """Use mock only when the configured Groq default has no key."""
        if self.default_provider == "groq" and (
            not self.groq_enabled or not self.groq_api_key
        ):
            self.default_provider = "mock"
