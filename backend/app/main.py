from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import auth, conversations, files, jobs, repos, search
from app.config import get_settings
from app.core.embeddings import _model, _tokenizer

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the embedding model at startup so the multi-minute cold
    # load/download happens once during container startup (before the
    # process accepts traffic) instead of blocking the event loop on the
    # first real search request.
    _tokenizer()
    _model()
    yield


app = FastAPI(title="Repo Analyzer API", version="0.1.0", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(repos.router)
app.include_router(jobs.router)
app.include_router(search.router)
app.include_router(files.router)
app.include_router(conversations.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
