from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://repoanalyzer:repoanalyzer@localhost:5432/repoanalyzer"
    redis_url: str = "redis://localhost:6379/0"

    jwt_private_key_path: str = "keys/jwt_private.pem"
    jwt_public_key_path: str = "keys/jwt_public.pem"
    jwt_algorithm: str = "RS256"
    jwt_access_token_expire_minutes: int = 60

    embedding_model_name: str = "microsoft/codebert-base"
    embedding_dimension: int = 768

    max_repo_size_mb: int = 500
    max_files_per_repo: int = 5000
    clone_timeout_seconds: int = 300

    rate_limit_analyze_per_minute: int = 5
    rate_limit_bucket_capacity: int = 5
    rate_limit_chat_per_minute: int = 15

    llm_provider: Literal["anthropic", "openai", "fake"] = "anthropic"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5-20250929"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"


@lru_cache
def get_settings() -> Settings:
    return Settings()
