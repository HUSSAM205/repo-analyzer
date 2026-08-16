from fastapi import FastAPI

from app.api.routes import auth
from app.config import get_settings

settings = get_settings()

app = FastAPI(title="Repo Analyzer API", version="0.1.0")

app.include_router(auth.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
