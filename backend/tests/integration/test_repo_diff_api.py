import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import File, Repo, RepoStatus
from app.db.session import async_session_maker
from app.main import app

pytestmark = pytest.mark.integration


async def _register_and_login(client: AsyncClient) -> tuple[str, str]:
    email = f"repo-diff-{uuid.uuid4()}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
    login_resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
    token = login_resp.json()["access_token"]
    me_resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return token, me_resp.json()["id"]


async def _create_ready_repo(user_id: str, name: str, files: list[tuple[str, str]]) -> str:
    async with async_session_maker() as db:
        repo = Repo(
            user_id=user_id, url=f"https://github.com/example/{name}-{uuid.uuid4()}", name=name,
            status=RepoStatus.READY,
        )
        db.add(repo)
        await db.flush()
        for path, content in files:
            db.add(File(repo_id=repo.id, path=path, content=content))
        await db.commit()
        return str(repo.id)


@pytest.mark.asyncio
async def test_compare_two_ready_repos_returns_metrics_and_deltas():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        repo_a_id = await _create_ready_repo(user_id, "repo-a", [("main.py", "def f():\n    return 1\n")])
        repo_b_id = await _create_ready_repo(
            user_id, "repo-b", [("main.py", "def f():\n    return 1\n"), ("utils.py", "def g():\n    return 2\n")]
        )
        resp = await client.get(
            "/api/v1/repos/compare",
            params={"repo_a": repo_a_id, "repo_b": repo_b_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["repo_a"]["repo_id"] == repo_a_id
        assert body["repo_b"]["repo_id"] == repo_b_id
        assert body["repo_a"]["metrics"]["file_count"] == 1
        assert body["repo_b"]["metrics"]["file_count"] == 2
        assert body["deltas"]["file_count_delta"] == 1
        assert body["security_verdict"]
        assert body["disclaimer"]


@pytest.mark.asyncio
async def test_compare_rejects_the_same_repo_twice():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        repo_id = await _create_ready_repo(user_id, "solo-repo", [("main.py", "x = 1\n")])
        resp = await client.get(
            "/api/v1/repos/compare",
            params={"repo_a": repo_id, "repo_b": repo_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_compare_returns_404_for_a_nonexistent_repo():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        repo_id = await _create_ready_repo(user_id, "only-repo", [("main.py", "x = 1\n")])
        resp = await client.get(
            "/api/v1/repos/compare",
            params={"repo_a": repo_id, "repo_b": str(uuid.uuid4())},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_compare_returns_409_when_a_repo_is_not_ready_yet():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        ready_id = await _create_ready_repo(user_id, "ready-repo", [("main.py", "x = 1\n")])
        async with async_session_maker() as db:
            pending_repo = Repo(
                user_id=user_id, url=f"https://github.com/example/pending-{uuid.uuid4()}", name="pending-repo",
                status=RepoStatus.PENDING,
            )
            db.add(pending_repo)
            await db.commit()
            pending_id = str(pending_repo.id)

        resp = await client.get(
            "/api/v1/repos/compare",
            params={"repo_a": ready_id, "repo_b": pending_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 409


@pytest.mark.asyncio
async def test_compare_requires_authentication():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, user_id = await _register_and_login(client)
        repo_a_id = await _create_ready_repo(user_id, "auth-a", [("main.py", "x = 1\n")])
        repo_b_id = await _create_ready_repo(user_id, "auth-b", [("main.py", "y = 2\n")])

        resp = await client.get(
            "/api/v1/repos/compare", params={"repo_a": repo_a_id, "repo_b": repo_b_id}
        )
        assert resp.status_code == 403
