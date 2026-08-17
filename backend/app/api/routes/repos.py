from uuid import UUID
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.arq_pool import get_arq_pool
from app.api.deps import get_current_user, get_repo_or_404
from app.core.rate_limit import enforce_analyze_rate_limit
from app.db.models import Job, Repo, RepoStatus, User
from app.db.session import get_db
from app.schemas.repos import RepoAnalyzeRequest, RepoAnalyzeResponse, RepoResponse

router = APIRouter(prefix="/api/v1/repos", tags=["repos"])


@router.post("/analyze", response_model=RepoAnalyzeResponse, status_code=status.HTTP_202_ACCEPTED)
async def analyze_repo_endpoint(
    payload: RepoAnalyzeRequest,
    current_user: Annotated[User, Depends(enforce_analyze_rate_limit)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RepoAnalyzeResponse:
    url_str = str(payload.repo_url)
    existing = await db.execute(select(Repo).where(Repo.user_id == current_user.id, Repo.url == url_str))
    repo = existing.scalar_one_or_none()
    if repo is None:
        repo = Repo(
            user_id=current_user.id,
            url=url_str,
            name=url_str.rstrip("/").rsplit("/", 1)[-1],
            status=RepoStatus.PENDING,
        )
        db.add(repo)
        await db.flush()

    job = Job(repo_id=repo.id)
    db.add(job)
    await db.commit()
    await db.refresh(job)

    pool = await get_arq_pool()
    await pool.enqueue_job("analyze_repo", str(job.id))

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
