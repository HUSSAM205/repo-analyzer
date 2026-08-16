from fastapi import FastAPI

from app.api.routes import auth, jobs, repos, search
from app.config import get_settings

settings = get_settings()

app = FastAPI(title="Repo Analyzer API", version="0.1.0")

app.include_router(auth.router)
app.include_router(repos.router)
app.include_router(jobs.router)
app.include_router(search.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
