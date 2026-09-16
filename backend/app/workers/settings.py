from arq.connections import RedisSettings

from app.config import get_settings
from app.core.embeddings import _model, _tokenizer
from app.workers.tasks import analyze_repo

settings = get_settings()


async def startup(ctx: dict) -> None:
    # Warm the embedding model once when the worker process starts, for the
    # same reason as the API's startup warm-up: avoid a multi-minute
    # cold-load blocking the first real job. Skippable (see Settings.
    # warm_embedding_model_on_startup) -- see app/main.py's lifespan for why.
    if settings.warm_embedding_model_on_startup:
        _tokenizer()
        _model()


class WorkerSettings:
    functions = [analyze_repo]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    job_timeout = 600
    max_jobs = 10
    # ARQ's own default poll_delay is 0.5s, and this worker runs in-process
    # for the lifetime of the web service (see Settings.run_worker_in_process
    # and main.py's lifespan) -- meaning it polls Redis for new jobs 24/7,
    # completely independent of real traffic. Each poll iteration issues 3
    # Redis commands (a zrangebyscore for due jobs, plus a 2-command pipeline
    # checking for aborted jobs -- see arq.worker.Worker._poll_iteration/
    # _cancel_aborted_jobs), which at the 0.5s default is ~518k commands/day
    # from idle polling alone -- enough on its own to exhaust a real Redis
    # command quota with zero actual usage. analyze_repo jobs already take
    # tens of seconds to minutes end to end (clone+parse+embed), and the
    # frontend polls job status via Postgres (GET /api/v1/jobs/{id}), not
    # Redis, at its own 2s interval -- so a few extra seconds of pickup
    # latency before a queued job starts running is imperceptible against
    # the job's own total runtime. 15s cuts idle command volume ~30x (to
    # ~17k/day) while keeping that latency negligible.
    poll_delay = 15
    # analyze_repo already marks Job and Repo FAILED on every failure path
    # (clone/chunk/embed errors, and a failed RUNNING transition -- see
    # app/workers/tasks.py). ARQ's default max_tries=5 would silently
    # re-enqueue and rerun the whole clone/chunk/embed pipeline from
    # scratch up to 5 times with no backoff and no visibility, fighting
    # with the job's own terminal status updates. Disable that.
    max_tries = 1
