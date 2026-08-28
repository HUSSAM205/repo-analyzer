import asyncio
import contextlib
import logging
import time
from contextlib import asynccontextmanager
from typing import Annotated

from arq.worker import create_worker
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import auth, chat, conversations, feedback, files, flagship, jobs, repos, search
from app.config import get_settings
from app.core.embeddings import _model, _tokenizer
from app.db.session import get_db
from app.workers.settings import WorkerSettings

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
    # first real search request. Skippable (see Settings.
    # warm_embedding_model_on_startup) for a memory-constrained deployment
    # where this process isn't the only one loading a copy of the model.
    if settings.warm_embedding_model_on_startup:
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

    # See Settings.run_worker_in_process for why this exists: on a
    # memory-constrained single-container deployment, running the ARQ
    # worker loop in this same process (sharing the one already-imported
    # copy of every heavy dependency) rather than as a second OS process is
    # the difference between fitting in 512MB and not.
    # handle_signals=False -- uvicorn already owns SIGTERM/SIGINT handling
    # for this process; a second handler here would fight it.
    worker = create_worker(WorkerSettings, handle_signals=False) if settings.run_worker_in_process else None
    worker_task = asyncio.create_task(worker.async_run()) if worker is not None else None

    yield

    if worker is not None and worker_task is not None:
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task
        await worker.close()


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


app = FastAPI(
    title="RepoLens AI API",
    description="AI-powered GitHub repository analysis and chat -- clones, parses, and indexes a "
    "repository's real AST, then answers questions by actually reading its code.",
    version="0.1.0",
    lifespan=lifespan,
)

# Applied to every response, success or error alike (this wraps the whole
# ASGI call chain, including Starlette's own exception handling, so an
# HTTPException-generated 4xx/5xx still gets these headers). This is a pure
# JSON API with no HTML templates or embeddable widget use case, so the CSP
# is maximally strict: no script/style/frame source is ever legitimate here.
# HSTS is safe to send unconditionally -- this service is only ever reached
# over HTTPS in every real deployment (Render terminates TLS at its edge).
_SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    for header, value in _SECURITY_HEADERS.items():
        response.headers[header] = value
    return response


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
app.include_router(flagship.router)
app.include_router(feedback.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/keepalive")
async def keepalive(db: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, str | float]:
    # Unauthenticated and deliberately trivial -- meant to be hit by an
    # external uptime pinger (e.g. cron-job.org, UptimeRobot) on both this
    # Render web service AND the Neon Postgres it talks to, both of which
    # independently spin down/suspend on their own idle timers on their
    # free tiers (confirmed live this session: a cold Render instance takes
    # ~1min to wake, and Neon's own suspend is a separate, additional
    # cold-start on top of that even once Render itself is up). A plain
    # `SELECT 1` is enough to keep the pooled connection warm without
    # touching real tables.
    started = time.monotonic()
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "database_roundtrip_ms": round((time.monotonic() - started) * 1000, 2)}
