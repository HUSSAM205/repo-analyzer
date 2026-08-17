import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.embeddings import embed_text
from app.db.models import CodeChunk, NodeType, Repo, RepoStatus
from app.db.session import async_session_maker
from app.main import app

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.mark.asyncio
async def test_search_endpoint_returns_matching_chunk():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        email = f"searchapi-{uuid.uuid4()}@example.com"
        await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
        login_resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        me_resp = await client.get("/api/v1/auth/me", headers=headers)
        user_id = me_resp.json()["id"]

        async with async_session_maker() as db:
            repo = Repo(user_id=user_id, url="https://github.com/example/repo2", name="repo2", status=RepoStatus.READY)
            db.add(repo)
            await db.flush()

            content = "def parse_config(path):\n    return open(path).read()"
            db.add(CodeChunk(
                repo_id=repo.id, file_path="config.py", symbol_name="parse_config", node_type=NodeType.FUNCTION,
                start_line=1, end_line=2, content=content, embedding=embed_text(content),
            ))
            await db.commit()
            repo_id = str(repo.id)

        resp = await client.post(
            "/api/v1/search", json={"repo_id": repo_id, "query": "parse configuration file"}, headers=headers
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) > 0
        assert results[0]["symbol_name"] == "parse_config"


@pytest.mark.asyncio
async def test_search_endpoint_accessible_by_other_users():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        owner_email = f"owner-{uuid.uuid4()}@example.com"
        await client.post("/api/v1/auth/register", json={"email": owner_email, "password": "supersecret123"})
        owner_login = await client.post("/api/v1/auth/login", json={"email": owner_email, "password": "supersecret123"})
        owner_token = owner_login.json()["access_token"]
        owner_me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {owner_token}"})
        owner_id = owner_me.json()["id"]

        async with async_session_maker() as db:
            repo = Repo(user_id=owner_id, url="https://github.com/example/private", name="private", status=RepoStatus.READY)
            db.add(repo)
            await db.commit()
            repo_id = str(repo.id)

        other_email = f"other-{uuid.uuid4()}@example.com"
        await client.post("/api/v1/auth/register", json={"email": other_email, "password": "supersecret123"})
        other_login = await client.post("/api/v1/auth/login", json={"email": other_email, "password": "supersecret123"})
        other_token = other_login.json()["access_token"]

        resp = await client.post(
            "/api/v1/search", json={"repo_id": repo_id, "query": "anything"},
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["results"] == []
