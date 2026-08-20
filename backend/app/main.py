import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

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


app = FastAPI(title="Repo Analyzer API", version="0.1.0", lifespan=lifespan)

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
