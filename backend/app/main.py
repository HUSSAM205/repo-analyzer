import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, chat, conversations, files, jobs, repos, search
from app.config import get_settings
from app.core.embeddings import _model, _tokenizer

settings = get_settings()
logger = logging.getLogger(__name__)

_PROVIDER_KEY_ATTRS = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "gemini": "gemini_api_key",
    "groq": "groq_api_key",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the embedding model at startup so the multi-minute cold
    # load/download happens once during container startup (before the
    # process accepts traffic) instead of blocking the event loop on the
    # first real search request.
    _tokenizer()
    _model()

    # Surface a fully misconfigured LLM provider at deploy time instead of
    # only discoverable by sending a chat message. Non-blocking: get_llm_client()
    # already falls back to another configured provider if one is usable, and
    # already raises a clear error at call time if none are -- this is just an
    # early, visible-in-logs heads-up.
    key_attr = _PROVIDER_KEY_ATTRS.get(settings.llm_provider)
    if key_attr is not None and not getattr(settings, key_attr):
        logger.warning(
            "LLM_PROVIDER=%s but %s is not configured; chat requests will "
            "rely on a fallback provider (if any are configured) or fail.",
            settings.llm_provider,
            key_attr.upper(),
        )

    yield


def parse_cors_origins(raw: str) -> tuple[list[str], bool]:
    """Parses Settings.cors_allowed_origins into (origins, allow_all).

    allow_all is True when "*" is present -- a wildcard origin can't be
    combined with credentialed requests (browsers reject
    "Access-Control-Allow-Origin: *" alongside
    "Access-Control-Allow-Credentials: true" outright), so callers must
    disable allow_credentials when this is True.
    """
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins, "*" in origins


app = FastAPI(title="Repo Analyzer API", version="0.1.0", lifespan=lifespan)

# Opt-in only -- see Settings.cors_allowed_origins for why this is empty by
# default (the frontend proxies every call server-side, so the browser
# never hits this API directly under the standard deployment).
_cors_origins, _allow_all_origins = parse_cors_origins(settings.cors_allowed_origins)
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if _allow_all_origins else _cors_origins,
        allow_credentials=not _allow_all_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth.router)
app.include_router(repos.router)
app.include_router(jobs.router)
app.include_router(search.router)
app.include_router(files.router)
app.include_router(conversations.router)
app.include_router(chat.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
