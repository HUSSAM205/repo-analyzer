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
    # Bounds the CodeBERT embedding step to the top N most substantive
    # source files (see ingestion.select_chunks_for_embedding) so analysis
    # finishes in seconds instead of minutes regardless of repo size --
    # list_directory/read_file (app/core/agent_tools.py) give the chat agent
    # full access to every file's raw content either way, embedding-capped
    # or not, so this only narrows search_code's index, not what the agent
    # can see.
    embedding_max_files: int = 15
    # A files-only cap isn't sufficient on its own -- confirmed live, a large
    # real repo's top-15 files alone still carried hundreds of chunks and
    # kept embedding running 100+ seconds. This caps total chunk count too
    # (see select_chunks_for_embedding); whichever limit is hit first wins.
    # Calibrated against real measurements on this deployment's CPU-only,
    # thread-throttled CodeBERT setup (see embedding_cpu_threads): ~2.7s per
    # chunk once the model is warm, so 20 chunks is roughly a 30-60s worst
    # case -- a real, bounded ceiling, not the sub-5-second figure a repo's
    # *file tree and briefing* actually hit (those no longer wait on
    # embedding at all, see analyze_repo's two-phase commit). Getting
    # embedding itself under 5s isn't physically achievable at this per-chunk
    # cost without capping chunks so low search_code would have almost
    # nothing to search -- lower this further only if literal near-zero
    # search coverage is an acceptable tradeoff, or embedding_cpu_threads is
    # raised (re-introducing the api-container-starving risk that setting
    # was deliberately added to prevent).
    embedding_max_chunks: int = 20

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
    # been retired in favor of the openai/gpt-oss-*/qwen/* families.
    # Also verified live across repeated real multi-turn tool-calling chats:
    # openai/gpt-oss-120b reliably (3/3 tries, on both trivial and
    # real-content repos) had Groq reject a later-turn search_code call with
    # a hard "Tool call validation failed: missing properties: 'query'"
    # APIError -- a genuine model-side reliability issue with this specific
    # model on Groq for this workload, not a formatting bug on our side
    # (the tool schema and message serialization are both correct). Of the
    # three real chat-capable models in Groq's current catalog,
    # qwen/qwen3.6-27b was the only one that never hit that error and
    # produced well-formed, evolving search queries with real content
    # discovery -- promoted to primary. openai/gpt-oss-20b never hit the
    # hard error either (though its search queries were weaker) and is kept
    # as the automatic fallback if qwen is ever retired (see
    # GroqClient._get_stream's NotFoundError handling) or misbehaves the
    # same way -- gpt-oss-120b is deliberately no longer used by default.
    groq_model: str = "qwen/qwen3.6-27b"
    groq_fallback_model: str | None = "openai/gpt-oss-20b"

    # Last-resort local fallback when Groq is rate-limited or unreachable
    # (see GroqClient.stream_chat) -- an empty string disables it (treated
    # as None by _build_provider_client), e.g. for a deployment with no
    # Ollama server. qwen2.5-coder is the default rather than deepseek-r1
    # because this fallback must support tool calling (search_code/
    # list_directory/read_file) -- confirmed against a real local Ollama
    # instance: qwen2.5-coder:7b reports "tools" in its capabilities,
    # deepseek-r1:7b does not.
    ollama_base_url: str = "http://host.docker.internal:11434/v1"
    ollama_model: str = "qwen2.5-coder:7b"


@lru_cache
def get_settings() -> Settings:
    return Settings()
