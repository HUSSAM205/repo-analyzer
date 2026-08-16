import shutil
import uuid
from pathlib import Path

import git
import pytest
from sqlalchemy import select

from app.db.models import CodeChunk, Job, JobStatus, Repo, RepoStatus, User
from app.db.session import async_session_maker
from app.workers.tasks import analyze_repo

pytestmark = [pytest.mark.integration, pytest.mark.slow]

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "sample_repo"


@pytest.fixture
def local_git_repo_url(tmp_path):
    repo_dir = tmp_path / "local_repo"
    shutil.copytree(FIXTURE_DIR, repo_dir)
    repo = git.Repo.init(repo_dir, initial_branch="main")
    # Exclude .git/* from the glob: rglob("*") runs after `init`, so without
    # this filter it would pick up git's own internal files (.git/HEAD,
    # .git/config, ...) and stage them as tracked blobs. That corrupts the
    # repo enough that a later local clone fails on Windows with "Untracked
    # working tree file '.git/HEAD' would be overwritten by merge".
    files = [
        str(p) for p in repo_dir.rglob("*")
        if p.is_file() and ".git" not in p.relative_to(repo_dir).parts
    ]
    repo.index.add(files)
    repo.index.commit("initial commit")
    yield str(repo_dir)


@pytest.mark.asyncio
async def test_analyze_repo_task_completes_and_stores_chunks(local_git_repo_url):
    async with async_session_maker() as db:
        user = User(email=f"worker-{uuid.uuid4()}@example.com", hashed_password="hashed")
        db.add(user)
        await db.flush()

        repo = Repo(user_id=user.id, url=local_git_repo_url, name="local-repo", status=RepoStatus.PENDING)
        db.add(repo)
        await db.flush()

        job = Job(repo_id=repo.id, status=JobStatus.PENDING)
        db.add(job)
        await db.commit()
        job_id = str(job.id)
        repo_id = repo.id
        user_id = user.id

    await analyze_repo({}, job_id)

    async with async_session_maker() as db:
        refreshed_job = await db.get(Job, uuid.UUID(job_id))
        assert refreshed_job.status == JobStatus.COMPLETED
        assert refreshed_job.progress == 100

        result = await db.execute(select(CodeChunk).where(CodeChunk.repo_id == repo_id))
        chunks = result.scalars().all()
        assert len(chunks) > 0
        assert any(c.symbol_name == "greet" for c in chunks)

        for chunk in chunks:
            await db.delete(chunk)
        await db.delete(refreshed_job)
        refreshed_repo = await db.get(Repo, repo_id)
        await db.delete(refreshed_repo)
        refreshed_user = await db.get(User, user_id)
        await db.delete(refreshed_user)
        await db.commit()


@pytest.mark.asyncio
async def test_analyze_repo_task_marks_failed_on_bad_url():
    async with async_session_maker() as db:
        user = User(email=f"worker-{uuid.uuid4()}@example.com", hashed_password="hashed")
        db.add(user)
        await db.flush()

        repo = Repo(user_id=user.id, url="/nonexistent/path/to/repo", name="bad-repo", status=RepoStatus.PENDING)
        db.add(repo)
        await db.flush()

        job = Job(repo_id=repo.id, status=JobStatus.PENDING)
        db.add(job)
        await db.commit()
        job_id = str(job.id)
        repo_id = repo.id
        user_id = user.id

    await analyze_repo({}, job_id)

    async with async_session_maker() as db:
        refreshed_job = await db.get(Job, uuid.UUID(job_id))
        assert refreshed_job.status == JobStatus.FAILED
        assert refreshed_job.error_message is not None

        await db.delete(refreshed_job)
        refreshed_repo = await db.get(Repo, repo_id)
        await db.delete(refreshed_repo)
        refreshed_user = await db.get(User, user_id)
        await db.delete(refreshed_user)
        await db.commit()
