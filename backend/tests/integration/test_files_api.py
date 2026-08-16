import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import File, Repo, RepoStatus
from app.db.session import async_session_maker
from app.main import app

pytestmark = pytest.mark.integration


async def _register_and_login(client: AsyncClient) -> str:
    email = f"files-{uuid.uuid4()}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
    login_resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
    return login_resp.json()["access_token"]


@pytest.mark.asyncio
async def test_file_tree_and_content_flow():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}

        me_resp = await client.get("/api/v1/auth/me", headers=headers)
        user_id = me_resp.json()["id"]

        async with async_session_maker() as db:
            repo = Repo(user_id=user_id, url="https://github.com/example/filesrepo", name="filesrepo", status=RepoStatus.READY)
            db.add(repo)
            await db.flush()
            db.add(File(repo_id=repo.id, path="src/main.py", content="def main(): pass"))
            db.add(File(repo_id=repo.id, path="src/utils/helpers.py", content="def helper(): pass"))
            db.add(File(repo_id=repo.id, path="README.md", content="# Hello"))
            await db.commit()
            repo_id = str(repo.id)

        tree_resp = await client.get(f"/api/v1/repos/{repo_id}/files", headers=headers)
        assert tree_resp.status_code == 200
        entries = tree_resp.json()["entries"]
        names_at_root = {e["name"] for e in entries}
        assert names_at_root == {"src", "README.md"}
        src_entry = next(e for e in entries if e["name"] == "src")
        assert src_entry["type"] == "directory"
        assert {c["name"] for c in src_entry["children"]} == {"main.py", "utils"}

        content_resp = await client.get(
            f"/api/v1/repos/{repo_id}/files/content", params={"path": "src/main.py"}, headers=headers
        )
        assert content_resp.status_code == 200
        assert content_resp.json()["content"] == "def main(): pass"

        missing_resp = await client.get(
            f"/api/v1/repos/{repo_id}/files/content", params={"path": "nope.py"}, headers=headers
        )
        assert missing_resp.status_code == 404


@pytest.mark.asyncio
async def test_files_endpoints_reject_other_users_repo():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        owner_token = await _register_and_login(client)
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        owner_me = await client.get("/api/v1/auth/me", headers=owner_headers)
        owner_id = owner_me.json()["id"]

        async with async_session_maker() as db:
            repo = Repo(user_id=owner_id, url="https://github.com/example/privatefiles", name="privatefiles", status=RepoStatus.READY)
            db.add(repo)
            await db.commit()
            repo_id = str(repo.id)

        other_token = await _register_and_login(client)
        other_headers = {"Authorization": f"Bearer {other_token}"}

        tree_resp = await client.get(f"/api/v1/repos/{repo_id}/files", headers=other_headers)
        assert tree_resp.status_code == 404

        content_resp = await client.get(
            f"/api/v1/repos/{repo_id}/files/content", params={"path": "anything.py"}, headers=other_headers
        )
        assert content_resp.status_code == 404
