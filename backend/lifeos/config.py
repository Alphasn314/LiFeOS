"""Process configuration for the LifeOS Core.

Configuration is intentionally small and environment driven.  Safety-sensitive
features retain conservative defaults even when this module is imported outside
the normal API process (for example by Alembic or a test runner).
"""

from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated Core configuration loaded from ``LIFEOS_*`` variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="LIFEOS_",
        extra="ignore",
    )

    database_url: str = (
        "postgresql+psycopg://lifeos:lifeos-dev-only@127.0.0.1:54329/lifeos"
    )
    display_timezone: str = "Asia/Shanghai"
    dry_run: bool = True
    real_enforcement_enabled: bool = False
    dev_auth_token: str = "change-me-before-nonlocal-use"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @field_validator("display_timezone")
    @classmethod
    def valid_display_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("display_timezone must be a valid IANA timezone") from exc
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the immutable-per-process settings snapshot."""

    return Settings()
