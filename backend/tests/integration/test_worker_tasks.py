import shutil
import uuid
from pathlib import Path

import git
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
        assert refreshed_job.stage == "completed"

        result = await db.execute(select(CodeChunk).where(CodeChunk.repo_id == repo_id))
        chunks = result.scalars().all()
        assert len(chunks) > 0
        assert any(c.symbol_name == "greet" for c in chunks)

        # The domain briefing is generated as part of the "parsing" stage
        # (see app.core.domain_briefing.generate_domain_briefing) and stored
        # on the repo row. It must always have the deterministic parts
        # populated -- file_type_distribution and tech_stack_badges never
        # depend on the LLM call succeeding -- and, since this test runs
        # against the real configured LLM provider (not mocked, per this
        # test's existing `slow`/`integration` markers), the qualitative
        # fields should also be populated rather than falling back to the
        # generic "Unclassified" briefing.
        refreshed_repo = await db.get(Repo, repo_id)
        briefing = refreshed_repo.domain_briefing
        assert briefing is not None
        assert isinstance(briefing["file_type_distribution"], list)
        assert briefing["file_type_distribution"]
        assert isinstance(briefing["tech_stack_badges"], list)
        assert briefing["primary_field"]
        assert briefing["target_audience"]
        assert briefing["architecture_overview"]

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
        # The job never got past the clone step, so its stage should still
        # read "cloning" (set right before clone_repo is called) -- it must
        # not have silently advanced to "parsing".
        assert refreshed_job.stage == "cloning"

        await db.delete(refreshed_job)
        refreshed_repo = await db.get(Repo, repo_id)
        await db.delete(refreshed_repo)
        refreshed_user = await db.get(User, user_id)
        await db.delete(refreshed_user)
        await db.commit()


@pytest.mark.asyncio
async def test_analyze_repo_task_progresses_through_all_four_stages_in_order(monkeypatch):
    # The heavy steps (clone_repo, walk_and_chunk, embed_chunks) and the LLM
    # call are stubbed out here so this test can verify the full stage
    # sequence -- "cloning" -> "parsing" -> "embedding" -> "completed" --
    # without paying for a real clone, the real CodeBERT model, or a real
    # LLM call (those are already exercised end-to-end, unmocked, by
    # test_analyze_repo_task_completes_and_stores_chunks above).
    from app.core.chunker import Chunk
    from app.core.ingestion import ChunkWithEmbedding, WalkedFile, WalkResult
    from app.core.llm import FakeLLMClient, ScriptedTurn
    from app.db.models import File
    from app.workers import tasks as tasks_module

    async with async_session_maker() as db:
        user = User(email=f"worker-{uuid.uuid4()}@example.com", hashed_password="hashed")
        db.add(user)
        await db.flush()

        repo = Repo(user_id=user.id, url="https://example.com/fake/stage-repo", name="fake-repo", status=RepoStatus.PENDING)
        db.add(repo)
        await db.flush()

        job = Job(repo_id=repo.id, status=JobStatus.PENDING)
        db.add(job)
        await db.commit()
        job_id = str(job.id)
        repo_id = repo.id
        user_id = user.id

    def fake_clone_repo(url, dest_dir, max_size_mb, timeout_seconds):
        dest_dir.mkdir(parents=True, exist_ok=True)
        return dest_dir

    fake_chunk = Chunk(
        file_path="main.py", symbol_name="greet", node_type="function", start_line=1, end_line=2,
        content="def greet(): pass",
    )
    fake_walk_result = WalkResult(
        chunks=[fake_chunk],
        files=[WalkedFile(path="main.py", content="def greet(): pass")],
        files_processed=1,
        files_skipped=0,
    )

    def fake_walk_and_chunk(root_dir, max_files):
        return fake_walk_result

    def fake_embed_chunks(chunks, batch_size=8):
        return [ChunkWithEmbedding(chunk=c, embedding=[0.0] * 768) for c in chunks]

    briefing_json = (
        '{"primary_field": "Test", "target_audience": "Testers", '
        '"architecture_overview": "Test overview.", "tech_stack_badges": []}'
    )

    monkeypatch.setattr(tasks_module, "clone_repo", fake_clone_repo)
    monkeypatch.setattr(tasks_module, "walk_and_chunk", fake_walk_and_chunk)
    monkeypatch.setattr(tasks_module, "embed_chunks", fake_embed_chunks)
    monkeypatch.setattr(
        tasks_module, "get_llm_client", lambda: FakeLLMClient(turns=[ScriptedTurn(text=briefing_json)])
    )

    observed_stages: list[str | None] = []
    original_commit = AsyncSession.commit

    async def recording_commit(self, *args, **kwargs):
        for obj in self.sync_session.identity_map.values():
            if isinstance(obj, Job) and str(obj.id) == job_id:
                observed_stages.append(obj.stage)
        return await original_commit(self, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "commit", recording_commit)
    try:
        await analyze_repo({}, job_id)
    finally:
        monkeypatch.undo()

    # Collapse consecutive duplicate observations (multiple commits can
    # happen while a given stage is still current, e.g. the progress=50
    # commit right after walk_and_chunk is still "parsing") down to the
    # unique sequence of stage values actually assigned, in order.
    unique_in_order = list(dict.fromkeys(observed_stages))
    assert unique_in_order == ["cloning", "parsing", "embedding", "completed"]

    async with async_session_maker() as db:
        refreshed_job = await db.get(Job, uuid.UUID(job_id))
        assert refreshed_job.status == JobStatus.COMPLETED
        assert refreshed_job.stage == "completed"

        refreshed_repo = await db.get(Repo, repo_id)
        assert refreshed_repo.domain_briefing["primary_field"] == "Test"

        chunk_result = await db.execute(select(CodeChunk).where(CodeChunk.repo_id == repo_id))
        for chunk in chunk_result.scalars().all():
            await db.delete(chunk)
        file_result = await db.execute(select(File).where(File.repo_id == repo_id))
        for f in file_result.scalars().all():
            await db.delete(f)
        await db.delete(refreshed_job)
        await db.delete(refreshed_repo)
        refreshed_user = await db.get(User, user_id)
        await db.delete(refreshed_user)
        await db.commit()


@pytest.mark.asyncio
async def test_analyze_repo_task_commits_files_and_briefing_before_embedding_starts(monkeypatch):
    # The core claim behind "instant ingestion": the file tree, code viewer,
    # and domain briefing card must not have to wait for embedding (the slow
    # step) to finish. Proves it concretely rather than trusting the code's
    # structure: a commit-hook (same technique as the stage-order test above)
    # records whether a commit has landed with File rows staged while the
    # job's stage is still "parsing" (i.e. the early files-commit, distinct
    # from the later stage="embedding" commit, which adds no new File rows).
    # embed_chunks -- called via asyncio.to_thread, so it must stay a plain
    # sync function, not a coroutine -- then checks that flag was already
    # set by the time it's invoked.
    from app.core.chunker import Chunk
    from app.core.ingestion import ChunkWithEmbedding, WalkedFile, WalkResult
    from app.core.llm import FakeLLMClient, ScriptedTurn
    from app.db.models import File
    from app.workers import tasks as tasks_module

    async with async_session_maker() as db:
        user = User(email=f"worker-{uuid.uuid4()}@example.com", hashed_password="hashed")
        db.add(user)
        await db.flush()

        repo = Repo(user_id=user.id, url=f"https://example.com/fake/early-commit-repo-{uuid.uuid4()}", name="fake-repo", status=RepoStatus.PENDING)
        db.add(repo)
        await db.flush()

        job = Job(repo_id=repo.id, status=JobStatus.PENDING)
        db.add(job)
        await db.commit()
        job_id = str(job.id)
        repo_id = repo.id
        user_id = user.id

    def fake_clone_repo(url, dest_dir, max_size_mb, timeout_seconds):
        dest_dir.mkdir(parents=True, exist_ok=True)
        return dest_dir

    fake_walk_result = WalkResult(
        chunks=[Chunk(file_path="main.py", symbol_name="greet", node_type="function", start_line=1, end_line=2, content="def greet(): pass")],
        files=[WalkedFile(path="main.py", content="def greet(): pass")],
        files_processed=1, files_skipped=0,
    )

    def fake_walk_and_chunk(root_dir, max_files):
        return fake_walk_result

    files_committed_while_still_parsing = {"value": False}
    embed_chunks_saw_files_already_committed = {"value": None}

    original_commit = AsyncSession.commit

    async def recording_commit(self, *args, **kwargs):
        # A File added via db.add() has no primary key yet -- and therefore
        # isn't in identity_map -- until commit()'s internal autoflush runs,
        # which happens *after* this hook's check (it wraps the call to
        # original_commit). session.new holds exactly these pending,
        # not-yet-flushed inserts, so both collections need checking.
        candidate_objects = list(self.sync_session.identity_map.values()) + list(self.sync_session.new)
        has_this_repos_files = any(isinstance(obj, File) and obj.repo_id == repo_id for obj in candidate_objects)
        job_obj = next(
            (obj for obj in self.sync_session.identity_map.values() if isinstance(obj, Job) and str(obj.id) == job_id),
            None,
        )
        if has_this_repos_files and job_obj is not None and job_obj.stage == "parsing":
            files_committed_while_still_parsing["value"] = True
        return await original_commit(self, *args, **kwargs)

    def fake_embed_chunks(chunks, batch_size=8):
        embed_chunks_saw_files_already_committed["value"] = files_committed_while_still_parsing["value"]
        return [ChunkWithEmbedding(chunk=c, embedding=[0.0] * 768) for c in chunks]

    briefing_json = (
        '{"primary_field": "Test", "target_audience": "Testers", '
        '"architecture_overview": "Test overview.", "tech_stack_badges": []}'
    )

    monkeypatch.setattr(tasks_module, "clone_repo", fake_clone_repo)
    monkeypatch.setattr(tasks_module, "walk_and_chunk", fake_walk_and_chunk)
    monkeypatch.setattr(tasks_module, "embed_chunks", fake_embed_chunks)
    monkeypatch.setattr(
        tasks_module, "get_llm_client", lambda: FakeLLMClient(turns=[ScriptedTurn(text=briefing_json)])
    )
    monkeypatch.setattr(AsyncSession, "commit", recording_commit)

    try:
        await analyze_repo({}, job_id)
    finally:
        monkeypatch.undo()

    assert embed_chunks_saw_files_already_committed["value"] is True

    async with async_session_maker() as db:
        refreshed_job = await db.get(Job, uuid.UUID(job_id))
        assert refreshed_job.status == JobStatus.COMPLETED

        refreshed_repo = await db.get(Repo, repo_id)
        assert refreshed_repo.domain_briefing["primary_field"] == "Test"

        file_result = await db.execute(select(File).where(File.repo_id == repo_id))
        files = file_result.scalars().all()
        assert [f.path for f in files] == ["main.py"]

        chunk_result = await db.execute(select(CodeChunk).where(CodeChunk.repo_id == repo_id))
        for chunk in chunk_result.scalars().all():
            await db.delete(chunk)
        for f in files:
            await db.delete(f)
        await db.delete(refreshed_job)
        await db.delete(refreshed_repo)
        refreshed_user = await db.get(User, user_id)
        await db.delete(refreshed_user)
        await db.commit()


@pytest.mark.asyncio
async def test_analyze_repo_task_marks_failed_when_running_transition_fails(monkeypatch):
    # Mirrors test_analyze_enqueue_failure_marks_job_failed in
    # test_repos_api.py, one step earlier in the pipeline: the RUNNING
    # status transition + its commit used to happen *before* the try/except
    # in analyze_repo, so a transient DB blip there (e.g. db.get(Repo, ...)
    # or the commit itself raising) would propagate uncaught out of the job
    # -- leaving both Job and Repo stuck PENDING forever, since all
    # failure-handling lived in the except blocks further down. Simulate
    # that blip by making the *first* AsyncSession.commit() call raise; it
    # must still be caught and both rows marked FAILED.
    async with async_session_maker() as db:
        user = User(email=f"worker-{uuid.uuid4()}@example.com", hashed_password="hashed")
        db.add(user)
        await db.flush()

        repo = Repo(
            user_id=user.id, url="/nonexistent/running-transition-blip", name="blip-repo",
            status=RepoStatus.PENDING,
        )
        db.add(repo)
        await db.flush()

        job = Job(repo_id=repo.id, status=JobStatus.PENDING)
        db.add(job)
        await db.commit()
        job_id = str(job.id)
        repo_id = repo.id
        user_id = user.id

    original_commit = AsyncSession.commit
    call_count = {"n": 0}

    async def flaky_commit(self, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated transient DB blip during RUNNING transition")
        return await original_commit(self, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "commit", flaky_commit)
    try:
        await analyze_repo({}, job_id)
    finally:
        monkeypatch.undo()

    async with async_session_maker() as db:
        refreshed_job = await db.get(Job, uuid.UUID(job_id))
        assert refreshed_job.status == JobStatus.FAILED
        assert refreshed_job.error_message is not None
        refreshed_repo = await db.get(Repo, repo_id)
        assert refreshed_repo.status == RepoStatus.FAILED

        await db.delete(refreshed_job)
        await db.delete(refreshed_repo)
        refreshed_user = await db.get(User, user_id)
        await db.delete(refreshed_user)
        await db.commit()


@pytest.mark.asyncio
async def test_analyze_repo_task_marks_failed_on_cancellation(monkeypatch):
    # Confirmed live: ARQ's job_timeout (WorkerSettings) enforces its
    # deadline by cancelling analyze_repo's task. asyncio.CancelledError
    # inherits from BaseException, not Exception -- so it silently skipped
    # every `except Exception` block below and left a real job/repo stuck
    # at RUNNING/embedding forever on a slow real analysis. Simulate the
    # same failure mode by having embed_chunks raise CancelledError (the
    # same exception type to_thread would propagate from a cancelled
    # worker task) and confirm it's now caught, both rows are marked
    # FAILED, and -- critically -- the CancelledError still propagates
    # (asyncio's cancellation contract requires this; swallowing it here
    # would be its own bug).
    import asyncio

    from app.workers import tasks as tasks_module

    async with async_session_maker() as db:
        user = User(email=f"worker-{uuid.uuid4()}@example.com", hashed_password="hashed")
        db.add(user)
        await db.flush()

        repo = Repo(
            user_id=user.id, url="https://example.com/fake/cancelled-repo", name="cancelled-repo",
            status=RepoStatus.PENDING,
        )
        db.add(repo)
        await db.flush()

        job = Job(repo_id=repo.id, status=JobStatus.PENDING)
        db.add(job)
        await db.commit()
        job_id = str(job.id)
        repo_id = repo.id
        user_id = user.id

    def fake_clone_repo(url, dest_dir, max_size_mb, timeout_seconds):
        dest_dir.mkdir(parents=True, exist_ok=True)
        return dest_dir

    def fake_walk_and_chunk(root_dir, max_files):
        from app.core.chunker import Chunk
        from app.core.ingestion import WalkedFile, WalkResult

        return WalkResult(
            chunks=[Chunk(
                file_path="main.py", symbol_name="greet", node_type="function", start_line=1, end_line=2,
                content="def greet(): pass",
            )],
            files=[WalkedFile(path="main.py", content="def greet(): pass")],
            files_processed=1, files_skipped=0,
        )

    def fake_embed_chunks(chunks, batch_size=8):
        raise asyncio.CancelledError()

    monkeypatch.setattr(tasks_module, "clone_repo", fake_clone_repo)
    monkeypatch.setattr(tasks_module, "walk_and_chunk", fake_walk_and_chunk)
    monkeypatch.setattr(tasks_module, "embed_chunks", fake_embed_chunks)
    try:
        with pytest.raises(asyncio.CancelledError):
            await analyze_repo({}, job_id)
    finally:
        monkeypatch.undo()

    async with async_session_maker() as db:
        refreshed_job = await db.get(Job, uuid.UUID(job_id))
        assert refreshed_job.status == JobStatus.FAILED
        assert refreshed_job.error_message == "Analysis timed out"
        refreshed_repo = await db.get(Repo, repo_id)
        assert refreshed_repo.status == RepoStatus.FAILED

        await db.delete(refreshed_job)
        await db.delete(refreshed_repo)
        refreshed_user = await db.get(User, user_id)
        await db.delete(refreshed_user)
        await db.commit()
