"""Application settings for the web adapter.

All configuration is environment-driven (``SPD_*`` variables, optionally from a
local ``.env`` file). ``.env.example`` at the repository root documents every
setting; no secrets are ever defaulted here or committed there.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENVIRONMENTS = ("development", "test", "production")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SPD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"

    # SQLite for local development (W1). The repository layer only ever sees a
    # SQLAlchemy URL, so PostgreSQL is a configuration change, not a code change.
    database_url: str = "sqlite:///./var/saudi_plot_api.db"

    cookie_name: str = "spd_session"
    # Secure=false is a local-development override only; production refuses it.
    cookie_secure: bool = True
    cookie_samesite: str = "lax"

    session_ttl_seconds: int = 7 * 24 * 3600

    # Root for all stored files (uploads, run outputs, renders). Every stored
    # path is confined to this directory; names are server-generated only.
    storage_root: Path = Path("./var/storage")

    # Explicit origin list. Cookies mean credentialed CORS, so "*" is refused.
    cors_origins: list[str] = []

    # ── Demo journey (W2) ───────────────────────────────────────────────
    # Deed uploads.
    upload_max_bytes: int = 20 * 1024 * 1024
    # Server-side Gemini. The key is read from the backend environment only
    # (GEMINI_API_KEY, or SPD_GEMINI_API_KEY) and never reaches any client.
    gemini_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GEMINI_API_KEY", "SPD_GEMINI_API_KEY", "gemini_api_key"),
    )
    gemini_extraction_model: str = "gemini-2.5-flash"
    gemini_render_model: str = "gemini-2.5-flash-image"
    gemini_timeout_seconds: float = 90.0
    # Advisory architectural-character knowledge (sbc_geo_knowledge sqlite).
    # Unset -> character resolution reports the knowledge base as unavailable.
    geo_knowledge_db: Path | None = None
    # Share links.
    share_ttl_seconds: int = 7 * 24 * 3600

    @field_validator("environment")
    @classmethod
    def _known_environment(cls, value: str) -> str:
        if value not in ENVIRONMENTS:
            raise ValueError(f"environment must be one of {ENVIRONMENTS}, got {value!r}")
        return value

    @field_validator("cookie_samesite")
    @classmethod
    def _known_samesite(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in ("lax", "strict", "none"):
            raise ValueError("cookie_samesite must be 'lax', 'strict', or 'none'")
        return normalized

    @field_validator("session_ttl_seconds")
    @classmethod
    def _positive_ttl(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("session_ttl_seconds must be positive")
        return value

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard_origins(cls, value: list[str]) -> list[str]:
        if "*" in value:
            raise ValueError(
                "cors_origins must list explicit origins; '*' is not allowed "
                "because the API uses credentialed (cookie) requests"
            )
        return value

    @model_validator(mode="after")
    def _production_requires_secure_cookies(self) -> Settings:
        if self.environment == "production" and not self.cookie_secure:
            raise ValueError("cookie_secure=false is a local-development override only")
        return self

    @model_validator(mode="after")
    def _samesite_none_requires_secure(self) -> Settings:
        # Browsers reject SameSite=None cookies without Secure; accepting the
        # combination would 201 on session creation and then 401 on everything.
        if self.cookie_samesite == "none" and not self.cookie_secure:
            raise ValueError("cookie_samesite='none' requires cookie_secure=true")
        return self
