from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.arq_pool import get_arq_pool
from app.core.rate_limit import enforce_analyze_rate_limit
from app.db.models import Job, Repo, RepoStatus, User
from app.db.session import get_db
from app.schemas.repos import RepoAnalyzeRequest, RepoAnalyzeResponse

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
