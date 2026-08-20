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
    # analyze_repo already marks Job and Repo FAILED on every failure path
    # (clone/chunk/embed errors, and a failed RUNNING transition -- see
    # app/workers/tasks.py). ARQ's default max_tries=5 would silently
    # re-enqueue and rerun the whole clone/chunk/embed pipeline from
    # scratch up to 5 times with no backoff and no visibility, fighting
    # with the job's own terminal status updates. Disable that.
    max_tries = 1
