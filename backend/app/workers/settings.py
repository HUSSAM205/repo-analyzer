from arq.connections import RedisSettings

from app.config import get_settings
from app.core.embeddings import _model, _tokenizer
from app.workers.tasks import analyze_repo

settings = get_settings()


async def startup(ctx: dict) -> None:
    # Warm the embedding model once when the worker process starts, for the
    # same reason as the API's startup warm-up: avoid a multi-minute
    # cold-load blocking the first real job.
    _tokenizer()
    _model()


class WorkerSettings:
    functions = [analyze_repo]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    job_timeout = 600
    max_jobs = 10
