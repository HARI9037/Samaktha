from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="Samaktha Core")
    app_version: str = Field(default="0.1.0")
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")
    sqlite_url: str = Field(default="sqlite:///./samaktha.db")

    model_config = SettingsConfigDict(env_prefix="SAMAKTHA_", env_file=".env")


@lru_cache
def get_settings() -> Settings:
    return Settings()
