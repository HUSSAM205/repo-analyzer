import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.arq_pool import get_arq_pool
from app.api.deps import get_current_user, get_repo_or_404
from app.core.rate_limit import enforce_analyze_rate_limit, enforce_ip_analyze_rate_limit
from app.core.repo_diff import compare_repos
from app.db.models import File, Job, JobStatus, Repo, RepoStatus, User
from app.db.session import get_db
from app.schemas.flagship import RepoCompareDeltas, RepoCompareResponse, RepoCompareSide, RepoMetrics
from app.schemas.repos import DomainBriefing, JobResponse, RepoAnalyzeRequest, RepoAnalyzeResponse, RepoResponse
from app.workers.tasks import analyze_repo

router = APIRouter(prefix="/api/v1/repos", tags=["repos"])
settings = get_settings()
logger = logging.getLogger(__name__)

# Fire-and-forget in-process fallback tasks (see _enqueue_or_fail_job),
# referenced here so they can't be garbage-collected mid-flight -- a
# well-known asyncio.create_task gotcha for a task whose only reference
# would otherwise be the local variable that creates it. Each discards
# itself via its own done-callback once finished.
_fallback_tasks: set[asyncio.Task] = set()

# Mirrors WorkerSettings.job_timeout (the ARQ path's own ceiling) -- with
# ARQ down, nothing else enforces a deadline on this coroutine, so a single
# stuck clone/embed step could otherwise run forever on a memory-constrained
# instance.
_FALLBACK_JOB_TIMEOUT_SECONDS = 600


async def _run_analysis_with_timeout(job_id: str) -> None:
    try:
        await asyncio.wait_for(analyze_repo({}, job_id), timeout=_FALLBACK_JOB_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        # analyze_repo's own `except asyncio.CancelledError` handler already
        # marked the Job/Repo FAILED ("Analysis timed out") by the time
        # wait_for's cancel-and-reraise reaches here -- nothing left to do.
        pass
    except Exception:
        # analyze_repo already catches and records every failure mode it
        # knows about (clone/chunk/embed errors, an unexpected exception --
        # see its own trailing `except Exception` in workers/tasks.py). This
        # is a last-resort net for something escaping that anyway, so it at
        # least lands in logs instead of becoming a silent "Task exception
        # was never retrieved" warning.
        logger.exception("In-process analysis fallback raised unexpectedly for job=%s", job_id)


def _schedule_in_process_analysis(job_id: str) -> None:
    task = asyncio.create_task(_run_analysis_with_timeout(job_id))
    _fallback_tasks.add(task)
    task.add_done_callback(_fallback_tasks.discard)


def _job_is_stale(job: Job) -> bool:
    # A PENDING/RUNNING job whose row is older than this has almost certainly
    # lost its worker (process died mid-run) or was never actually enqueued.
    # clone_timeout_seconds is how long the clone step alone is allowed to
    # take; doubling it gives headroom for the chunk/embed steps that follow
    # cloning in the same job, while still catching a truly abandoned job.
    threshold = timedelta(seconds=settings.clone_timeout_seconds * 2)
    created_at = job.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - created_at > threshold


async def _load_ready_files_or_409(db: AsyncSession, repo: Repo) -> list[File]:
    if repo.status != RepoStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This repository hasn't finished analyzing yet.",
        )
    result = await db.execute(select(File).where(File.repo_id == repo.id))
    return list(result.scalars().all())


async def _enqueue_or_fail_job(db: AsyncSession, repo: Repo, job: Job) -> None:
    try:
        pool = await get_arq_pool()
        await pool.enqueue_job("analyze_repo", str(job.id))
        return
    except Exception:
        logger.warning(
            "ARQ enqueue failed for job=%s (Redis unavailable?) -- falling back to in-process execution",
            job.id, exc_info=True,
        )

    # Redis/ARQ is unreachable (e.g. an exhausted Upstash quota) -- rather
    # than fail the whole request, run the exact same analyze_repo()
    # coroutine directly on this process's event loop instead of handing it
    # to ARQ. It reads nothing from ARQ's `ctx` (see workers/tasks.py) and
    # already persists every status/progress update straight to Postgres
    # (which is also all GET /jobs/{id} polling ever reads), so from the
    # frontend's point of view this is indistinguishable from the normal
    # ARQ-dispatched path -- just without ARQ's own retry supervision (its
    # timeout half is replicated by _run_analysis_with_timeout above).
    try:
        _schedule_in_process_analysis(str(job.id))
    except Exception as exc:
        # Only reachable if asyncio.create_task itself fails outright (e.g.
        # a genuinely broken event loop) -- at that point there truly is no
        # way to run this job, so it must be marked FAILED like before.
        job.status = JobStatus.FAILED
        job.error_message = "Failed to start analysis job"
        repo.status = RepoStatus.FAILED
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to start analysis job",
        ) from exc


@router.post(
    "/analyze",
    response_model=RepoAnalyzeResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(enforce_ip_analyze_rate_limit)],
)
async def analyze_repo_endpoint(
    payload: RepoAnalyzeRequest,
    current_user: Annotated[User, Depends(enforce_analyze_rate_limit)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RepoAnalyzeResponse:
    url_str = str(payload.repo_url)
    existing = await db.execute(select(Repo).where(Repo.url == url_str))
    repo = existing.scalar_one_or_none()

    if repo is not None and repo.status != RepoStatus.FAILED:
        # Someone already analyzed this URL (or is currently analyzing it) --
        # converge onto that repo's existing analysis instead of paying the
        # clone/chunk/embed/LLM cost again. Find its most recent job rather
        # than enqueueing a new one.
        latest_job = await db.execute(
            select(Job).where(Job.repo_id == repo.id).order_by(Job.created_at.desc()).limit(1)
        )
        job = latest_job.scalar_one()
        is_stale = repo.status == RepoStatus.PENDING and job.status in (
            JobStatus.PENDING,
            JobStatus.RUNNING,
        ) and _job_is_stale(job)
        if not is_stale:
            return RepoAnalyzeResponse(repo_id=repo.id, job_id=job.id)
        # else: the repo's latest job is stale (worker died mid-run, or the
        # job was never picked up) -- fall through to re-analyze, exactly
        # like the FAILED-repo path below.

    if repo is None:
        repo = Repo(
            user_id=current_user.id,
            url=url_str,
            name=url_str.rstrip("/").rsplit("/", 1)[-1],
            status=RepoStatus.PENDING,
        )
        db.add(repo)
        try:
            await db.flush()
        except IntegrityError:
            # Someone else concurrently submitted this same brand-new URL and
            # won the race -- roll back our failed insert and converge onto
            # their (now-committed) repo/job instead of surfacing a 500.
            await db.rollback()
            winner = await db.execute(select(Repo).where(Repo.url == url_str))
            repo = winner.scalar_one()
            winner_job = await db.execute(
                select(Job).where(Job.repo_id == repo.id).order_by(Job.created_at.desc()).limit(1)
            )
            job = winner_job.scalar_one()
            return RepoAnalyzeResponse(repo_id=repo.id, job_id=job.id)
    # else: repo exists and is FAILED (or stale) -- fall through to
    # re-analyze it below, exactly as the pre-existing re-analysis path
    # already did.

    job = Job(repo_id=repo.id)
    db.add(job)
    await db.commit()
    await db.refresh(job)

    await _enqueue_or_fail_job(db, repo, job)

    return RepoAnalyzeResponse(repo_id=repo.id, job_id=job.id)


@router.get("", response_model=list[RepoResponse])
async def list_repos(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Repo]:
    result = await db.execute(
        select(Repo).where(Repo.user_id == current_user.id).order_by(Repo.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/compare", response_model=RepoCompareResponse)
async def compare_repos_endpoint(
    repo_a: UUID,
    repo_b: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RepoCompareResponse:
    # Registered ABOVE get_repo below on purpose: Starlette matches routes
    # in registration order, and "/compare" would otherwise be swallowed by
    # "/{repo_id}" (repo_id="compare" fails UUID validation with a 422
    # before ever reaching this route) if it came after it.
    if repo_a == repo_b:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose two different repositories to compare.",
        )

    repo_a_obj = await get_repo_or_404(db, repo_a, current_user)
    repo_b_obj = await get_repo_or_404(db, repo_b, current_user)

    files_a = await _load_ready_files_or_409(db, repo_a_obj)
    files_b = await _load_ready_files_or_409(db, repo_b_obj)

    result = compare_repos(files_a, files_b)
    return RepoCompareResponse(
        repo_a=RepoCompareSide(
            repo_id=str(repo_a_obj.id), name=repo_a_obj.name, url=repo_a_obj.url,
            metrics=RepoMetrics.model_validate(result["metrics_a"]),
        ),
        repo_b=RepoCompareSide(
            repo_id=str(repo_b_obj.id), name=repo_b_obj.name, url=repo_b_obj.url,
            metrics=RepoMetrics.model_validate(result["metrics_b"]),
        ),
        deltas=RepoCompareDeltas.model_validate(result["deltas"]),
        security_verdict=result["security_verdict"],
        disclaimer=result["disclaimer"],
    )


@router.get("/{repo_id}", response_model=RepoResponse)
async def get_repo(
    repo_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RepoResponse:
    repo = await get_repo_or_404(db, repo_id, current_user)

    latest_job_result = await db.execute(
        select(Job).where(Job.repo_id == repo.id).order_by(Job.created_at.desc()).limit(1)
    )
    latest_job = latest_job_result.scalar_one_or_none()

    return RepoResponse(
        id=repo.id,
        url=repo.url,
        name=repo.name,
        status=repo.status,
        created_at=repo.created_at,
        latest_job=JobResponse.model_validate(latest_job) if latest_job is not None else None,
        domain_briefing=DomainBriefing.model_validate(repo.domain_briefing) if repo.domain_briefing else None,
    )
