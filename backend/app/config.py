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
    # PyTorch defaults to using every visible CPU core for intra-op
    # parallelism. Uncapped, a single embedding batch pegs all cores on the
    # host (confirmed live: 594% CPU sustained for minutes on a 12-core
    # dev box), starving every other container sharing the same Docker
    # Desktop VM -- including the api container, which is how a background
    # analysis job turns into user-facing "server unavailable" errors on
    # chat/annotation requests. Capped well below the host's core count so
    # embedding always leaves real headroom for the rest of the stack.
    embedding_cpu_threads: int = 4

    max_repo_size_mb: int = 500
    max_files_per_repo: int = 5000
    clone_timeout_seconds: int = 300

    rate_limit_analyze_per_minute: int = 5
    rate_limit_bucket_capacity: int = 5
    rate_limit_chat_per_minute: int = 15

    llm_provider: Literal["anthropic", "openai", "gemini", "groq", "fake"] = "anthropic"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5-20250929"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.7-flash"
    groq_api_key: str | None = None
    # Verified live against GET https://api.groq.com/openai/v1/models: as of
    # this deployment, Groq's catalog no longer includes any Llama 3.x model
    # (llama-3.3-70b-versatile / llama-3.1-8b-instant both 404) -- they've
    # been retired in favor of the openai/gpt-oss-* and qwen/* families.
    # groq_model is the primary (verified working, tool-calling-capable);
    # groq_fallback_model is used automatically if Groq ever retires this
    # one too (see GroqClient._get_stream's NotFoundError handling).
    groq_model: str = "openai/gpt-oss-120b"
    groq_fallback_model: str | None = "openai/gpt-oss-20b"


@lru_cache
def get_settings() -> Settings:
    return Settings()
