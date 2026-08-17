import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.db.models import Job, Repo, RepoStatus
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
