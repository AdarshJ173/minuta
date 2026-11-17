"""Process-wide settings. Everything secret comes from the environment, never code."""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    env: str = "dev"
    log_level: str = "INFO"
    log_format: str = "json"
    public_base_url: str = "http://localhost:8000"
    allowed_hosts: str = ""

    database_url: str = Field(..., alias="DATABASE_URL")
    supabase_url: str = ""

    r2_endpoint: str = Field(..., alias="R2_ENDPOINT")
    r2_bucket_name: str = Field(..., alias="R2_BUCKET_NAME")
    r2_access_key_id: str = Field(..., alias="R2_ACCESS_KEY_ID")
    r2_secret_access_key: str = Field(..., alias="R2_SECRET_ACCESS_KEY")
    r2_region: str = "auto"

    youtube_api_key: str = Field(..., alias="YOUTUBE_API_KEY")
    youtube_daily_quota_units: int = 10000
    youtube_quota_reserve_units: int = 500

    # Comma-separated provider order, first match wins.
    # Known providers: apify, yta, ytdlp, supadata.
    transcript_provider_order: str = "yta"
    transcript_languages: str = "en"
    transcript_max_attempts: int = 6
    supadata_api_key: str = ""
    apify_api_token: str = ""

    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_version: str = "v1"
    embedding_dimensions: int = 384
    embedding_batch_size: int = 32

    chunk_target_chars: int = 2600
    chunk_overlap_chars: int = 350
    chunk_max_chars: int = 4000
    processing_version: int = 1

    sync_interval_minutes: int = 360
    sync_max_videos_per_run: int = 200
    worker_poll_seconds: int = 5
    worker_concurrency: int = 4
    job_max_attempts: int = 6

    rate_limit_read_per_minute: int = 120
    rate_limit_research_per_hour: int = 20
    max_page_size: int = 100
    default_page_size: int = 20
    max_transcript_page_segments: int = 300
    full_transcript_max_chars: int = 60000

    research_model_provider: str = ""
    research_model_name: str = ""
    research_api_key: str = ""
    research_base_url: str = ""
    research_max_transcripts: int = 500
    research_max_tokens_per_job: int = 2_000_000

    admin_bootstrap_token: str = ""

    @field_validator("database_url")
    @classmethod
    def _validate_db_url(cls, v: str) -> str:
        if not v.startswith(("postgresql://", "postgres://")):
            raise ValueError("DATABASE_URL must be a postgres connection string")
        if not urlparse(v).hostname:
            raise ValueError("DATABASE_URL is missing a host")
        return v

    @field_validator("public_base_url")
    @classmethod
    def _validate_base_url(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def tx_provider_order(self) -> list[str]:
        return [p.strip() for p in self.transcript_provider_order.split(",") if p.strip()]

    @property
    def languages(self) -> list[str]:
        return [p.strip() for p in self.transcript_languages.split(",") if p.strip()]

    @property
    def host_allowlist(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    def redaction_values(self) -> list[str]:
        values = [
            self.youtube_api_key,
            self.r2_access_key_id,
            self.r2_secret_access_key,
            self.research_api_key,
            self.supadata_api_key,
            self.apify_api_token,
            self.admin_bootstrap_token,
        ]
        if parsed := urlparse(self.database_url):
            if parsed.password:
                values.append(parsed.password)
        return [v for v in values if v and len(v) >= 6]


@lru_cache
def get_settings() -> Settings:
    return Settings()
