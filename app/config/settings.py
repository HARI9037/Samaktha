from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__


class Settings(BaseSettings):
    app_name: str = Field(default="Samaktha Core")
    app_version: str = Field(default_factory=lambda: __version__)
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")
    # P2.7 — structured logging: "text" (default) or "json".
    log_format: str = Field(default="text")
    sqlite_url: str = Field(default="sqlite:///data/memory.db")
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000)

    # P1.5 — HTTP execution layer limits.
    api_max_request_bytes: int = Field(default=256_000)
    api_rate_limit_per_minute: int = Field(default=60)
    api_execute_timeout_seconds: float = Field(default=300.0)

    # P2.2 — Plugin SDK: where locally installed plugins live.
    plugin_dir: str = Field(default="samaktha_plugins")

    # P2.8 — Personality: the default/startup profile id and where the
    # runtime-switched selection is persisted across restarts.
    personality_profile: str = Field(default="samaktha-core")
    personality_state_path: str = Field(default="data/personality_state.json")

    model_config = SettingsConfigDict(env_prefix="SAMAKTHA_", env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def resolve_sqlite_path(sqlite_url: str) -> str:
    """Resolve a ``sqlite:///`` URL (or a plain filesystem path) to a path.

    ``sqlite_url`` is the single source of truth for the memory database
    location. Only local sqlite URLs (``sqlite:///...``) and plain paths are
    supported.
    """
    prefix = "sqlite:///"
    if sqlite_url.startswith(prefix):
        return sqlite_url[len(prefix):]
    if sqlite_url.startswith("sqlite://"):
        raise ValueError(
            "Only local sqlite URLs (sqlite:///...) or plain filesystem paths "
            "are supported."
        )
    return sqlite_url
