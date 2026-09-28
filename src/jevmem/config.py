"""Application configuration, loaded from environment variables and `.env`.

Secrets are held as `SecretStr` so they never appear in reprs, logs, or manifests.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Jev (TypeSafe System One), reached via OpenRouter by default -------
    jev_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("JEV_API_KEY", "OPENROUTER_API_KEY", "TYPESAFE_API_KEY"),
    )
    jev_base_url: str = "https://openrouter.ai/api"
    # Pin the dated snapshot: aliases like `jev-latest` move without notice.
    jev_model: str = "typesafe/jev-1.13-20260917"
    jev_max_concurrency: int = Field(default=16, ge=1, le=256)
    jev_timeout_s: float = Field(default=30.0, gt=0)
    jev_max_retries: int = Field(default=4, ge=0, le=10)

    # --- Qwen (OpenAI-compatible) -------------------------------------------
    qwen_base_url: str | None = None
    qwen_api_key: SecretStr | None = None
    qwen_model: str | None = None
    qwen_max_concurrency: int = Field(default=16, ge=1, le=256)
    qwen_timeout_s: float = Field(default=120.0, gt=0)
    qwen_max_retries: int = Field(default=3, ge=0, le=10)
    qwen_enable_thinking: bool = False

    # --- Optional baselines --------------------------------------------------
    embedding_model: str = "Qwen/Qwen3-Embedding-0.6B"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    # --- Application ---------------------------------------------------------
    data_dir: Path = Path("data")
    memory_context_token_budget: int = Field(default=1024, ge=32)
    log_level: str = "INFO"
    environment: Literal["development", "production", "test"] = "development"

    @property
    def cache_path(self) -> Path:
        return self.data_dir / "cache" / "responses.sqlite3"

    def public_dict(self) -> dict[str, Any]:
        """Configuration safe to publish (manifests, `/config/public`): secrets are dropped."""
        data = self.model_dump(mode="json")
        return {k: v for k, v in data.items() if "key" not in k}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
