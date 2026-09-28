from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _csv(value: object) -> object:
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    data_dir: Path = Path("./data")

    llm_provider: Literal["gemini", "demo"] = "gemini"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.8-flash"
    gemini_fallback_model: str | None = "gemini-3.5-flash-lite"
    gemini_thinking_level: Literal["minimal", "low", "medium", "high"] | None = "low"
    llm_timeout_s: float = Field(default=30.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0, le=5)

    query_timeout_ms: int = Field(default=3000, ge=100)
    max_result_rows: int = Field(default=1000, ge=1, le=50_000)
    max_concurrent_queries: int = Field(default=8, ge=1)
    repair_attempts: int = Field(default=1, ge=0, le=3)
    cache_size: int = Field(default=512, ge=0)
    cache_ttl_s: int = Field(default=3600, ge=0)

    max_upload_mb: int = Field(default=10, ge=1, le=100)
    max_upload_rows: int = Field(default=200_000, ge=1)
    max_upload_columns: int = Field(default=100, ge=1)
    max_datasets_per_client: int = Field(default=10, ge=1)
    dataset_ttl_days: int = Field(default=7, ge=1)

    rate_limit_per_minute: int = Field(default=30, ge=1)
    trusted_proxy_hops: int = Field(default=0, ge=0, le=5)
    cors_origins: Annotated[list[str], NoDecode, BeforeValidator(_csv)] = ["http://localhost:5173"]
    serve_frontend: bool = True
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _check(self) -> "Settings":
        if self.environment == "production":
            if self.llm_provider == "gemini" and not self.gemini_api_key:
                raise ValueError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini in production")
            if any("*" in o for o in self.cors_origins):
                raise ValueError("CORS_ORIGINS must list explicit origins in production")
        return self

    @property
    def datasets_dir(self) -> Path:
        return self.data_dir / "datasets"

    @property
    def app_db_path(self) -> Path:
        return self.data_dir / "app.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
