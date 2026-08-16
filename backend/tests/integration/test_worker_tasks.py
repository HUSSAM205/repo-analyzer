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
async def test_analyze_repo_task_reanalysis_does_not_duplicate_chunks(local_git_repo_url):
    # Mirrors what POST /repos/analyze does for a repeat analysis: reuse the
    # same Repo row, create a fresh Job against it. The chunk count after the
    # second analyze_repo run must equal the count after the first, not
    # double it.
    async with async_session_maker() as db:
        user = User(email=f"worker-{uuid.uuid4()}@example.com", hashed_password="hashed")
        db.add(user)
        await db.flush()

        repo = Repo(user_id=user.id, url=local_git_repo_url, name="local-repo", status=RepoStatus.PENDING)
        db.add(repo)
        await db.flush()

        first_job = Job(repo_id=repo.id, status=JobStatus.PENDING)
        db.add(first_job)
        await db.commit()
        first_job_id = str(first_job.id)
        repo_id = repo.id
        user_id = user.id

    await analyze_repo({}, first_job_id)

    async with async_session_maker() as db:
        result = await db.execute(select(CodeChunk).where(CodeChunk.repo_id == repo_id))
        count_after_first = len(result.scalars().all())
        assert count_after_first > 0

        second_job = Job(repo_id=repo_id, status=JobStatus.PENDING)
        db.add(second_job)
        await db.commit()
        second_job_id = str(second_job.id)

    await analyze_repo({}, second_job_id)

    async with async_session_maker() as db:
        refreshed_second_job = await db.get(Job, uuid.UUID(second_job_id))
        assert refreshed_second_job.status == JobStatus.COMPLETED

        result = await db.execute(select(CodeChunk).where(CodeChunk.repo_id == repo_id))
        chunks_after_second = result.scalars().all()
        assert len(chunks_after_second) == count_after_first

        for chunk in chunks_after_second:
            await db.delete(chunk)
        first_job_row = await db.get(Job, uuid.UUID(first_job_id))
        await db.delete(first_job_row)
        await db.delete(refreshed_second_job)
        refreshed_repo = await db.get(Repo, repo_id)
        await db.delete(refreshed_repo)
        refreshed_user = await db.get(User, user_id)
        await db.delete(refreshed_user)
        await db.commit()


@pytest.mark.asyncio
async def test_analyze_repo_task_reanalysis_does_not_duplicate_files(local_git_repo_url):
    from app.db.models import File

    async with async_session_maker() as db:
        user = User(email=f"worker-{uuid.uuid4()}@example.com", hashed_password="hashed")
        db.add(user)
        await db.flush()

        repo = Repo(user_id=user.id, url=local_git_repo_url, name="local-repo", status=RepoStatus.PENDING)
        db.add(repo)
        await db.flush()

        job1 = Job(repo_id=repo.id, status=JobStatus.PENDING)
        db.add(job1)
        await db.commit()
        job1_id = str(job1.id)
        repo_id = repo.id
        user_id = user.id

    await analyze_repo({}, job1_id)

    async with async_session_maker() as db:
        result = await db.execute(select(File).where(File.repo_id == repo_id))
        count_after_first = len(result.scalars().all())
        assert count_after_first > 0

        job2 = Job(repo_id=repo_id, status=JobStatus.PENDING)
        db.add(job2)
        await db.commit()
        job2_id = str(job2.id)

    await analyze_repo({}, job2_id)

    async with async_session_maker() as db:
        result = await db.execute(select(File).where(File.repo_id == repo_id))
        files_after_second = result.scalars().all()
        assert len(files_after_second) == count_after_first

        for f in files_after_second:
            await db.delete(f)
        result = await db.execute(select(Job).where(Job.repo_id == repo_id))
        for job in result.scalars().all():
            await db.delete(job)
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
