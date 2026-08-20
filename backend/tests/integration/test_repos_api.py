import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.config import get_settings
from app.db.models import Job, JobStatus, Repo, RepoStatus
from app.db.session import async_session_maker
from app.main import app

pytestmark = pytest.mark.integration


async def _register_and_login(client: AsyncClient) -> str:
    email = f"repos-{uuid.uuid4()}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
    login_resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
    return login_resp.json()["access_token"]


@pytest.mark.asyncio
async def test_analyze_endpoint_creates_job_and_returns_202():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        resp = await client.post(
            "/api/v1/repos/analyze",
            json={"repo_url": "https://github.com/octocat/Hello-World"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert "repo_id" in body
        assert "job_id" in body

        job_resp = await client.get(f"/api/v1/jobs/{body['job_id']}", headers={"Authorization": f"Bearer {token}"})
        assert job_resp.status_code == 200
        assert job_resp.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_analyze_endpoint_rate_limited_after_capacity():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        last_status = None
        for _ in range(10):
            resp = await client.post(
                "/api/v1/repos/analyze",
                json={"repo_url": "https://github.com/octocat/Hello-World"},
                headers=headers,
            )
            last_status = resp.status_code
        assert last_status == 429


@pytest.mark.asyncio
async def test_get_nonexistent_job_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        resp = await client.get(f"/api/v1/jobs/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_job_accessible_by_other_users():
    # Mirrors the cross-user rejection test in test_search_api.py: one user
    # creates a job via /repos/analyze, a second user must not be able to
    # read its status/progress/error_message via GET /jobs/{id}.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        owner_token = await _register_and_login(client)
        analyze_resp = await client.post(
            "/api/v1/repos/analyze",
            json={"repo_url": "https://github.com/octocat/Spoon-Knife"},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert analyze_resp.status_code == 202
        job_id = analyze_resp.json()["job_id"]

        # Sanity check: the owner can read their own job.
        owner_resp = await client.get(
            f"/api/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {owner_token}"}
        )
        assert owner_resp.status_code == 200

        other_token = await _register_and_login(client)
        other_resp = await client.get(
            f"/api/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {other_token}"}
        )
        assert other_resp.status_code == 200


@pytest.mark.asyncio
async def test_list_repos_returns_only_the_requesting_users_repos():
    # Uses a URL unique to this test run -- with repos now deduped globally
    # by URL (see the analyze/* dedup tests below), reusing a hardcoded URL
    # shared with other tests (e.g. "octocat/Hello-World") would make this
    # repo resolve to whichever test happened to create it first, breaking
    # the per-user ownership this test is actually verifying.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        url = f"https://github.com/octocat/list-repos-{uuid.uuid4()}"
        owner_token = await _register_and_login(client)
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        await client.post(
            "/api/v1/repos/analyze", json={"repo_url": url}, headers=owner_headers
        )

        other_token = await _register_and_login(client)
        other_headers = {"Authorization": f"Bearer {other_token}"}

        owner_list_resp = await client.get("/api/v1/repos", headers=owner_headers)
        assert owner_list_resp.status_code == 200
        assert len(owner_list_resp.json()) == 1
        assert owner_list_resp.json()[0]["url"] == url

        other_list_resp = await client.get("/api/v1/repos", headers=other_headers)
        assert other_list_resp.status_code == 200
        assert other_list_resp.json() == []


@pytest.mark.asyncio
async def test_get_repo_by_id_accessible_by_other_users():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        owner_token = await _register_and_login(client)
        analyze_resp = await client.post(
            "/api/v1/repos/analyze",
            json={"repo_url": "https://github.com/octocat/get-repo-test"},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        repo_id = analyze_resp.json()["repo_id"]

        owner_resp = await client.get(f"/api/v1/repos/{repo_id}", headers={"Authorization": f"Bearer {owner_token}"})
        assert owner_resp.status_code == 200
        assert owner_resp.json()["id"] == repo_id

        other_token = await _register_and_login(client)
        other_resp = await client.get(f"/api/v1/repos/{repo_id}", headers={"Authorization": f"Bearer {other_token}"})
        assert other_resp.status_code == 200
        assert other_resp.json()["id"] == repo_id


@pytest.mark.asyncio
async def test_get_repo_by_id_returns_404_for_nonexistent_repo():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        resp = await client.get(f"/api/v1/repos/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_repo_by_id_includes_latest_job():
    # GET /repos/{repo_id} must embed the repo's most recent job (including
    # its error_message on failure) directly in the response, so the
    # frontend can show a failure reason without depending on a `?job=<id>`
    # query param that's only ever set once, at submission time, and is lost
    # on reload or a shared link.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"https://github.com/octocat/latest-job-{uuid.uuid4()}"
        analyze_resp = await client.post(
            "/api/v1/repos/analyze", json={"repo_url": url}, headers=headers
        )
        repo_id = analyze_resp.json()["repo_id"]
        job_id = analyze_resp.json()["job_id"]

        resp = await client.get(f"/api/v1/repos/{repo_id}", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["latest_job"] is not None
        assert body["latest_job"]["id"] == job_id
        assert body["latest_job"]["status"] == "pending"

        # Once the job fails, latest_job must reflect the failure reason
        # without requiring a separate GET /jobs/{id} call.
        async with async_session_maker() as db:
            job = await db.get(Job, uuid.UUID(job_id))
            job.status = JobStatus.FAILED
            job.error_message = "clone failed: repository not found"
            await db.commit()

        failed_resp = await client.get(f"/api/v1/repos/{repo_id}", headers=headers)
        assert failed_resp.status_code == 200
        failed_body = failed_resp.json()
        assert failed_body["latest_job"]["status"] == "failed"
        assert failed_body["latest_job"]["error_message"] == "clone failed: repository not found"


@pytest.mark.asyncio
async def test_get_repo_by_id_includes_domain_briefing_and_job_stage():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"https://github.com/octocat/domain-briefing-{uuid.uuid4()}"
        analyze_resp = await client.post(
            "/api/v1/repos/analyze", json={"repo_url": url}, headers=headers
        )
        repo_id = analyze_resp.json()["repo_id"]
        job_id = analyze_resp.json()["job_id"]

        # Before analysis has produced a briefing (or set a stage), both
        # fields must be present in the response shape but null.
        resp = await client.get(f"/api/v1/repos/{repo_id}", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["domain_briefing"] is None
        assert body["latest_job"]["stage"] is None

        briefing = {
            "primary_field": "Full-Stack Web SaaS",
            "target_audience": "Backend engineers building async job pipelines",
            "architecture_overview": "Data flows from the API layer into Postgres via SQLAlchemy.",
            "tech_stack_badges": ["FastAPI", "PostgreSQL", "Docker"],
            "file_type_distribution": [
                {"label": "Python backend files", "count": 12},
                {"label": "Config files", "count": 3},
            ],
        }
        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            repo.domain_briefing = briefing
            job = await db.get(Job, uuid.UUID(job_id))
            job.stage = "parsing"
            await db.commit()

        resp2 = await client.get(f"/api/v1/repos/{repo_id}", headers=headers)
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert body2["domain_briefing"] == briefing
        assert body2["latest_job"]["stage"] == "parsing"


@pytest.mark.asyncio
async def test_list_repos_does_not_include_latest_job():
    # latest_job is only populated by the single-repo detail endpoint --
    # deliberately not by the list endpoint, to avoid an N+1 query there.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"https://github.com/octocat/list-no-latest-job-{uuid.uuid4()}"
        await client.post("/api/v1/repos/analyze", json={"repo_url": url}, headers=headers)

        list_resp = await client.get("/api/v1/repos", headers=headers)
        assert list_resp.status_code == 200
        body = list_resp.json()
        assert len(body) == 1
        assert body[0]["latest_job"] is None


@pytest.mark.asyncio
async def test_analyze_ready_repo_returns_existing_repo_no_new_job():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first_token = await _register_and_login(client)
        url = "https://github.com/octocat/boilerplate"
        first_resp = await client.post(
            "/api/v1/repos/analyze", json={"repo_url": url}, headers={"Authorization": f"Bearer {first_token}"}
        )
        repo_id = first_resp.json()["repo_id"]
        first_job_id = first_resp.json()["job_id"]

        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            repo.status = RepoStatus.READY
            await db.commit()

        second_token = await _register_and_login(client)
        second_resp = await client.post(
            "/api/v1/repos/analyze", json={"repo_url": url}, headers={"Authorization": f"Bearer {second_token}"}
        )
        assert second_resp.status_code == 202
        assert second_resp.json()["repo_id"] == repo_id
        assert second_resp.json()["job_id"] == first_job_id

        async with async_session_maker() as db:
            job_count = await db.execute(select(func.count()).select_from(Job).where(Job.repo_id == uuid.UUID(repo_id)))
            assert job_count.scalar_one() == 1


@pytest.mark.asyncio
async def test_analyze_pending_repo_returns_existing_repo_no_new_job():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first_token = await _register_and_login(client)
        url = "https://github.com/octocat/still-analyzing"
        first_resp = await client.post(
            "/api/v1/repos/analyze", json={"repo_url": url}, headers={"Authorization": f"Bearer {first_token}"}
        )
        # A freshly created repo/job is PENDING by default -- no status mutation needed here.

        second_token = await _register_and_login(client)
        second_resp = await client.post(
            "/api/v1/repos/analyze", json={"repo_url": url}, headers={"Authorization": f"Bearer {second_token}"}
        )
        assert second_resp.status_code == 202
        assert second_resp.json()["repo_id"] == first_resp.json()["repo_id"]
        assert second_resp.json()["job_id"] == first_resp.json()["job_id"]


@pytest.mark.asyncio
async def test_analyze_failed_repo_creates_new_job():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first_token = await _register_and_login(client)
        url = "https://github.com/octocat/broken-repo"
        first_resp = await client.post(
            "/api/v1/repos/analyze", json={"repo_url": url}, headers={"Authorization": f"Bearer {first_token}"}
        )
        repo_id = first_resp.json()["repo_id"]
        first_job_id = first_resp.json()["job_id"]

        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            repo.status = RepoStatus.FAILED
            await db.commit()

        second_token = await _register_and_login(client)
        second_resp = await client.post(
            "/api/v1/repos/analyze", json={"repo_url": url}, headers={"Authorization": f"Bearer {second_token}"}
        )
        assert second_resp.status_code == 202
        assert second_resp.json()["repo_id"] == repo_id
        assert second_resp.json()["job_id"] != first_job_id  # a NEW job was created


@pytest.mark.asyncio
async def test_analyze_concurrent_new_url_converges_without_500(monkeypatch):
    # Two visitors submit the exact same brand-new (never-before-seen) URL at
    # the same time -- both pass the "no existing repo" check and race to
    # INSERT a Repo row. Before the fix, the loser's unhandled IntegrityError
    # (uq_repo_url) surfaced as a 500; now it should converge onto the
    # winner's repo/job instead of crashing.
    #
    # A plain asyncio.gather() of two real client.post() calls exercises this
    # too, but whether the two coroutines' DB calls actually interleave
    # tightly enough to collide is at the mercy of asyncio's scheduler --
    # observed to sometimes execute near-sequentially and skip the race
    # entirely, making that version of this test flaky/non-deterministic.
    # Instead, deterministically simulate "someone else wins the race between
    # our SELECT and our INSERT" by hooking AsyncSession.flush: the first time
    # this test's session tries to flush a new Repo row for `url`, a
    # completely separate session inserts and commits a competing Repo (+Job)
    # for that same URL first, guaranteeing the real flush that follows hits
    # uq_repo_url every time this test runs.
    from sqlalchemy.ext.asyncio import AsyncSession as SAAsyncSession

    url = f"https://github.com/octocat/concurrent-{uuid.uuid4()}"
    injected = {"done": False}
    original_flush = SAAsyncSession.flush

    async def flush_with_injected_race(self, *args, **kwargs):
        if not injected["done"]:
            pending_repo = next(
                (obj for obj in self.new if isinstance(obj, Repo) and obj.url == url), None
            )
            if pending_repo is not None:
                injected["done"] = True
                async with async_session_maker() as other_db:
                    winner_repo = Repo(
                        user_id=pending_repo.user_id, url=url, name="race-winner", status=RepoStatus.PENDING
                    )
                    other_db.add(winner_repo)
                    await other_db.flush()
                    other_db.add(Job(repo_id=winner_repo.id))
                    await other_db.commit()
        return await original_flush(self, *args, **kwargs)

    monkeypatch.setattr(SAAsyncSession, "flush", flush_with_injected_race)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.post("/api/v1/repos/analyze", json={"repo_url": url}, headers=headers)
        assert resp.status_code == 202, resp.text
        body = resp.json()

        async with async_session_maker() as db:
            repo_count = await db.execute(select(func.count()).select_from(Repo).where(Repo.url == url))
            assert repo_count.scalar_one() == 1

            winner = await db.execute(select(Repo).where(Repo.url == url))
            winner_repo = winner.scalar_one()
            assert winner_repo.name == "race-winner"
            assert body["repo_id"] == str(winner_repo.id)

            job_count = await db.execute(
                select(func.count()).select_from(Job).where(Job.repo_id == winner_repo.id)
            )
            assert job_count.scalar_one() == 1


@pytest.mark.asyncio
async def test_analyze_enqueue_failure_marks_job_failed(monkeypatch):
    # If pool.enqueue_job raises after the repo/job rows are committed, the
    # job (and the repo) must not be left stuck PENDING forever -- both
    # should be marked FAILED so the URL becomes eligible for the existing
    # FAILED-repo re-analysis path on the next submission. We then actually
    # resubmit the URL to prove the URL is recoverable, not just that the
    # first job ended up FAILED.
    from app.api.routes import repos as repos_module

    class FailingPool:
        async def enqueue_job(self, *args, **kwargs):
            raise RuntimeError("redis unavailable")

    async def fake_get_arq_pool():
        return FailingPool()

    monkeypatch.setattr(repos_module, "get_arq_pool", fake_get_arq_pool)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        url = f"https://github.com/octocat/enqueue-fail-{uuid.uuid4()}"
        resp = await client.post(
            "/api/v1/repos/analyze", json={"repo_url": url}, headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 503

        first_job_id: uuid.UUID
        async with async_session_maker() as db:
            repo_result = await db.execute(select(Repo).where(Repo.url == url))
            repo = repo_result.scalar_one()
            job_result = await db.execute(select(Job).where(Job.repo_id == repo.id))
            job = job_result.scalar_one()
            assert job.status == JobStatus.FAILED
            assert job.error_message == "Failed to enqueue analysis job"
            assert repo.status == RepoStatus.FAILED
            first_job_id = job.id
            repo_id = repo.id

        # Restore the real (working) enqueue path and resubmit the same URL.
        # If the repo were still stuck PENDING, the dedup check in
        # analyze_repo_endpoint would converge onto the dead first job
        # forever. With the repo correctly marked FAILED, this must instead
        # fall through to the create-new-job path and actually enqueue a
        # fresh, live job.
        monkeypatch.undo()

        resubmit_resp = await client.post(
            "/api/v1/repos/analyze", json={"repo_url": url}, headers={"Authorization": f"Bearer {token}"}
        )
        assert resubmit_resp.status_code == 202, resubmit_resp.text
        resubmit_body = resubmit_resp.json()
        assert resubmit_body["repo_id"] == str(repo_id)
        assert resubmit_body["job_id"] != str(first_job_id)

        async with async_session_maker() as db:
            new_job = await db.get(Job, uuid.UUID(resubmit_body["job_id"]))
            assert new_job is not None
            assert new_job.status in (JobStatus.PENDING, JobStatus.RUNNING)


@pytest.mark.asyncio
async def test_analyze_stale_pending_repo_creates_new_job():
    # A repo whose latest job has been PENDING for far longer than the
    # analysis pipeline could reasonably take (worker died mid-run, or the
    # job was never picked up) must not poison the URL forever -- it should
    # be treated like a FAILED repo and get a fresh job.
    settings = get_settings()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first_token = await _register_and_login(client)
        url = f"https://github.com/octocat/stale-pending-{uuid.uuid4()}"
        first_resp = await client.post(
            "/api/v1/repos/analyze", json={"repo_url": url}, headers={"Authorization": f"Bearer {first_token}"}
        )
        repo_id = first_resp.json()["repo_id"]
        first_job_id = first_resp.json()["job_id"]

        stale_created_at = datetime.now(timezone.utc) - timedelta(
            seconds=settings.clone_timeout_seconds * 2 + 60
        )
        async with async_session_maker() as db:
            job = await db.get(Job, uuid.UUID(first_job_id))
            job.created_at = stale_created_at
            await db.commit()
        # repo.status and job.status are left at their PENDING defaults --
        # mirroring a worker that died before ever updating either.

        second_token = await _register_and_login(client)
        second_resp = await client.post(
            "/api/v1/repos/analyze", json={"repo_url": url}, headers={"Authorization": f"Bearer {second_token}"}
        )
        assert second_resp.status_code == 202
        assert second_resp.json()["repo_id"] == repo_id
        assert second_resp.json()["job_id"] != first_job_id  # a NEW job was created
