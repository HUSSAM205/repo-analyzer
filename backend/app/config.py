from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://repoanalyzer:repoanalyzer@localhost:5432/repoanalyzer"
    redis_url: str = "redis://localhost:6379/0"

    @field_validator("database_url")
    @classmethod
    def _ensure_asyncpg_driver(cls, value: str) -> str:
        # Managed Postgres providers (Render, Railway, etc) hand out a plain
        # "postgresql://" (or Heroku-style "postgres://") connection string
        # -- SQLAlchemy's async engine needs the "+asyncpg" driver suffix
        # explicitly, or create_async_engine raises at startup with no
        # asyncpg dialect found. Normalizing here means the provider's
        # connection string can be pasted in as-is, with zero manual editing.
        for prefix in ("postgresql://", "postgres://"):
            if value.startswith(prefix):
                return "postgresql+asyncpg://" + value[len(prefix):]
        return value

    jwt_private_key_path: str = "keys/jwt_private.pem"
    jwt_public_key_path: str = "keys/jwt_public.pem"
    # Inline alternative to the file-path settings above -- lets a platform
    # whose env vars are settable via API/CLI (Render, Railway, etc.) skip
    # the file-upload step (Render's "Secret Files") entirely. Accepts
    # either the raw PEM text or a base64 encoding of it (some platforms/
    # tools mangle embedded newlines in env var values; base64 sidesteps
    # that). Takes priority over the path settings when set -- see
    # app/core/security.py's _load_pem.
    jwt_private_key: str | None = None
    jwt_public_key: str | None = None
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
    # Both the api process (search's query embedding) and the worker
    # process (bulk repo embedding) eagerly load their own separate copy of
    # the ~500MB CodeBERT model at startup by default -- fine with two
    # separate containers, but confirmed live to OOM ("Out of memory (used
    # over 512Mi)") when both run in one free-tier container together (see
    # backend/scripts/start_unified.sh). Set false there specifically: the
    # model still loads correctly on first actual use (embed_texts calls
    # the same lazily-cached _tokenizer()/_model()), it just pays the cold
    # -load cost on that first request instead of at startup.
    warm_embedding_model_on_startup: bool = True
    # Runs the ARQ worker loop inside the api process's own event loop
    # (see app/main.py's lifespan) instead of as a separate `arq` process.
    # Exists for the same free-tier-container reason as the setting above,
    # and supersedes it: confirmed live that even with eager warm-up
    # disabled, two separate OS processes each importing their own copy of
    # torch/transformers/langchain/langgraph was enough on its own to OOM a
    # 512MB instance -- only one process, one import of each library,
    # actually fit. False (two separate processes/services) remains
    # correct for docker-compose and any deployment with a real worker
    # plan, where the CPU/memory isolation is worth having.
    run_worker_in_process: bool = False
    # Confirmed live: loading the real ~500MB CodeBERT model during the
    # embedding step (not just importing torch/transformers, which the two
    # settings above already handle) is what actually exceeds a free-tier
    # 512MB instance's memory -- the job got silently killed mid-embedding
    # even with both settings above enabled. False skips the embedding
    # step entirely (analyze_repo goes straight from committing files to
    # COMPLETED) and excludes the now-useless search_code tool from chat
    # (see app/api/routes/chat.py) -- list_directory/read_file still give
    # the chat agent full access to every file, just without vector
    # similarity search. True (the default) is correct everywhere memory
    # isn't this tight.
    enable_embedding: bool = True

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
    # Chat gets its own, more generous bucket -- confirmed live: the shared
    # capacity=5 bucket (sized for the much heavier /repos/analyze endpoint,
    # which clones+parses+embeds a whole repo) let a normal back-and-forth
    # conversation exhaust its burst allowance by the 3rd-5th message and
    # start returning 429 "Rate limit exceeded for chat messages" -- visually
    # indistinguishable from an LLM-provider outage to the user, even though
    # the LLM call was never reached. A single chat turn is a bounded,
    # comparatively cheap operation (one or a few LLM calls), so it can
    # tolerate a much larger burst without materially changing this
    # deployment's abuse exposure.
    rate_limit_chat_bucket_capacity: int = 20
    rate_limit_chat_per_minute: int = 30

    # IP-based limits (see rate_limit.py's enforce_ip_*_rate_limit) -- a
    # second, independent gate on top of the per-user limits above, keyed by
    # client IP so a single source can't bypass the per-user ceiling by
    # cycling through this app's free/instant guest accounts. Sized higher
    # than the per-user limits: an IP can legitimately represent many real
    # users behind NAT/a shared office network, so this is a DDoS/abuse
    # backstop, not the primary per-user throttle.
    rate_limit_ip_analyze_per_minute: int = 10
    rate_limit_ip_analyze_bucket_capacity: int = 10
    rate_limit_ip_chat_per_minute: int = 60
    rate_limit_ip_chat_bucket_capacity: int = 60

    llm_provider: Literal["anthropic", "openai", "gemini", "groq", "fake"] = "anthropic"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5-20250929"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"
    gemini_api_key: str | None = None
    # Verified live against the real Gemini API on 2026-08-24 while wiring
    # up Gemini as Tier 1 (see llm_providers.py's DualProviderClient):
    # gemini-3.7-flash (the newest model) returned a genuine
    # "503 UNAVAILABLE -- currently experiencing high demand" / read-timeout
    # from Google's own infrastructure on repeated attempts -- not a key or
    # quota problem. gemini-2.5-flash 404'd outright: "This model
    # models/gemini-2.5-flash is no longer available to new users" (this
    # key's account tier only has the 3.x line). gemini-3.6-flash -- Google's
    # own suggested replacement in that 404 message -- worked cleanly on
    # every attempt, including a full multi-turn tool-calling exchange.
    gemini_model: str = "gemini-3.6-flash"
    groq_api_key: str | None = None
    # Re-verified live against GET https://api.groq.com/openai/v1/models on
    # 2026-08-23: llama-3.3-70b-versatile / llama-3.1-8b-instant (the
    # "fastest Groq model" names most documentation/requests suggest) still
    # 404 -- Groq's real current catalog for this account has no Llama 3.x
    # model at all. Of what's actually available, the realistic chat-capable
    # candidates are qwen/qwen3.6-27b, openai/gpt-oss-20b, and
    # openai/gpt-oss-120b (allam-2-7b is Arabic-specialized; groq/compound*
    # are Groq's own agentic systems with their own built-in tools, not a
    # plain chat-completions model this codebase's tool-calling loop should
    # drive directly).
    #
    # Earlier live testing (see prior revision of this comment) found
    # qwen/qwen3.6-27b the most *reliable* of the three -- gpt-oss-120b
    # repeatedly failed later-turn tool calls with a hard "Tool call
    # validation failed" APIError, and gpt-oss-20b's search queries were
    # comparatively weaker. That earlier choice optimized for answer
    # quality/thoroughness. This revision optimizes for latency instead (an
    # explicit product decision, paired with agent.py's MAX_TOOL_ITERATIONS
    # drop from 8 to 4 and its new per-tool TOOL_TIMEOUT_SECONDS): gpt-oss-20b
    # is the smaller of the two models that never hit the hard tool-call
    # error, and a smaller model is meaningfully faster to the first token
    # and per-token on Groq's LPU hardware. qwen/qwen3.6-27b moves to
    # fallback -- GroqClient._get_stream already switches to it automatically
    # on a 404 (retirement) or 429 (quota exhaustion), so this keeps that
    # same safety net while the default path is the faster model.
    groq_model: str = "openai/gpt-oss-20b"
    groq_fallback_model: str | None = "qwen/qwen3.6-27b"

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

    # Feedback dispatch via Resend's HTTP API (see core/feedback_email.py) --
    # chosen over raw SMTP for the same reason this app already prefers
    # managed HTTP APIs over protocol-level integrations elsewhere
    # (Groq/Gemini for the LLM, Upstash for Redis): one API key, no
    # server/port/TLS credential juggling. resend_api_key still must be set
    # (a real secret, so no sensible default) for feedback email to
    # actually send; if it's missing, submissions are still accepted (202)
    # and logged server-side, never a failed request for whoever took the
    # time to submit feedback -- see feedback.py's route. An env var still
    # overrides this default in the normal pydantic-settings way, so a
    # deployment that wants a different inbox can just set
    # FEEDBACK_RECIPIENT_EMAIL.
    resend_api_key: str | None = None
    feedback_recipient_email: str = "hossammotasem2005@gmail.com"
    # Resend requires the "from" address to be on a domain verified with
    # them -- defaults to their own shared sandbox sender (works
    # out-of-the-box with any Resend account, no domain verification
    # needed) unless a verified custom address is configured.
    feedback_sender_email: str = "RepoLens AI <onboarding@resend.dev>"

    # Comma-separated list of browser origins allowed to call this API
    # directly (e.g. "https://myapp.vercel.app,https://myapp.com"), or "*"
    # for any origin. Empty by default -- this app's current frontend
    # proxies every backend call server-side (see frontend/lib/backend.ts's
    # BACKEND_URL), so the browser never calls this API directly and no
    # CORS headers are needed. Set this only if something calls the API
    # straight from a browser (a different frontend, direct API usage,
    # etc). See app/main.py for how "*" is handled (credentials are
    # disabled in that case -- required by the CORS spec, not optional).
    cors_allowed_origins: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
