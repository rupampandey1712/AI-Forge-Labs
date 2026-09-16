"""Application configuration.

WHY pydantic-settings: configuration is the first place a service breaks in
production ("works locally"), and the cheapest fix is to fail loudly at import
time rather than to hand ``None`` to a database driver at request #10,000.
Every field below is typed, validated, and documented, and the object is
constructed exactly once (see ``get_settings``).

TRADEOFF: a module-level singleton is convenient but makes tests awkward, so we
expose an ``lru_cache``d accessor instead — tests call
``get_settings.cache_clear()`` after patching the environment.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent

AppEnv = Literal["development", "test", "production"]
SandboxMode = Literal["subprocess", "docker", "disabled"]
LLMProvider = Literal["mock", "anthropic", "openai", "gemini", "google"]
EmbeddingProviderName = Literal["hash", "gemini", "google", "openai"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application -------------------------------------------------------
    app_env: AppEnv = "development"
    app_debug: bool = True
    app_name: str = "AI Forge Labs"
    api_v1_prefix: str = "/api/v1"

    # --- Security ----------------------------------------------------------
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(64))
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30

    # --- Persistence -------------------------------------------------------
    # Empty string => SQLite fallback, so a fresh clone runs with zero
    # infrastructure. Docker Compose supplies the Postgres URL.
    database_url: str = ""
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    redis_url: str = "redis://localhost:6379/0"
    cache_enabled: bool = True

    # --- HTTP --------------------------------------------------------------
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    rate_limit_per_minute: int = 240

    # --- Sandbox -----------------------------------------------------------
    sandbox_mode: SandboxMode = "subprocess"
    sandbox_timeout_seconds: float = 8.0
    sandbox_memory_mb: int = 256
    sandbox_max_output_bytes: int = 64 * 1024
    sandbox_docker_image: str = "aiforge-sandbox:latest"
    sandbox_max_concurrency: int = 4

    # --- AI ----------------------------------------------------------------
    # "mock" is the default on purpose: every AI lab in the game must be
    # playable with no key and no network. Setting a provider upgrades the
    # experience; it never unlocks content.
    llm_provider: LLMProvider = "mock"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    #: Leave blank to use each provider's default model (see app/ai/llm).
    llm_model: str = ""
    llm_timeout_seconds: float = 45.0
    #: Hard ceiling on tokens per request so a runaway prompt cannot generate
    #: a surprise bill. The LLM Lab teaches exactly this control.
    llm_max_tokens: int = 2048

    #: "hash" is a deterministic offline embedder. It is lexical-only, and the
    #: RAG Tower uses that limitation deliberately: players hit the paraphrase
    #: wall, then switch providers and watch precision jump.
    embedding_provider: EmbeddingProviderName = "hash"
    embedding_dimensions: int = 256

    # --- Labs --------------------------------------------------------------
    #: Attention visualiser defaults. Small enough to render, large enough that
    #: multi-head behaviour is visible.
    attention_d_model: int = 64
    attention_heads: int = 4
    attention_max_tokens: int = 48
    #: Guard on agent runs started from the UI.
    agent_recursion_limit: int = 25

    # --- Observability -----------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = False

    # --- Gameplay tuning ---------------------------------------------------
    daily_mission_size: int = 9
    retention_decay_check_hours: int = 6

    @field_validator("secret_key")
    @classmethod
    def _reject_weak_secret_in_prod(cls, v: str, info) -> str:
        env = (info.data or {}).get("app_env", "development")
        if env == "production" and (len(v) < 32 or "change-me" in v):
            raise ValueError(
                "SECRET_KEY must be a strong, non-default value in production. "
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(64))"'
            )
        return v

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sqlalchemy_url(self) -> str:
        """Resolved async database URL.

        WHY the fallback: the single most common reason a learning project never
        gets run is "install Postgres first". SQLite + aiosqlite gives an
        identical SQLAlchemy programming model for a solo player, and Compose
        still runs the real Postgres path that the SQL/Alembic missions need.
        """
        if self.database_url:
            return self.database_url
        if self.app_env == "test":
            return "sqlite+aiosqlite:///:memory:"
        return f"sqlite+aiosqlite:///{(BACKEND_ROOT / 'aiforge.db').as_posix()}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_sqlite(self) -> bool:
        return self.sqlalchemy_url.startswith("sqlite")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def llm_configured(self) -> bool:
        """True when a real provider *and* its key are both present."""
        return {
            "anthropic": bool(self.anthropic_api_key),
            "openai": bool(self.openai_api_key),
            "gemini": bool(self.gemini_api_key),
            "google": bool(self.gemini_api_key),
        }.get(self.llm_provider, False)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton (cached; clear it in tests)."""
    return Settings()


settings = get_settings()
