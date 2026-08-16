from arq.connections import RedisSettings

from app.config import get_settings
from app.workers.tasks import analyze_repo

settings = get_settings()


class WorkerSettings:
    functions = [analyze_repo]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    job_timeout = 600
    max_jobs = 10
