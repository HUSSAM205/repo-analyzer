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
from app.core.rate_limit import enforce_analyze_rate_limit
from app.db.models import Job, JobStatus, Repo, RepoStatus, User
from app.db.session import get_db
from app.schemas.repos import RepoAnalyzeRequest, RepoAnalyzeResponse, RepoResponse

router = APIRouter(prefix="/api/v1/repos", tags=["repos"])
settings = get_settings()


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


async def _enqueue_or_fail_job(db: AsyncSession, repo: Repo, job: Job) -> None:
    pool = await get_arq_pool()
    try:
        await pool.enqueue_job("analyze_repo", str(job.id))
    except Exception as exc:
        # The repo/job rows are already committed at this point. If enqueue
        # fails, the job must not be left silently PENDING forever -- mark it
        # (and the repo) FAILED so the next submission of this URL takes the
        # existing FAILED-repo re-analysis path instead of reusing a job that
        # will never run.
        job.status = JobStatus.FAILED
        job.error_message = "Failed to enqueue analysis job"
        repo.status = RepoStatus.FAILED
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to enqueue analysis job",
        ) from exc


@router.post("/analyze", response_model=RepoAnalyzeResponse, status_code=status.HTTP_202_ACCEPTED)
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


@router.get("/{repo_id}", response_model=RepoResponse)
async def get_repo(
    repo_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Repo:
    return await get_repo_or_404(db, repo_id, current_user)
