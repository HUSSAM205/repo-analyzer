import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import Repo, RepoStatus
from app.db.session import async_session_maker
from app.main import app

pytestmark = pytest.mark.integration


async def _register_and_login(client: AsyncClient) -> str:
    email = f"conv-{uuid.uuid4()}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
    login_resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
    return login_resp.json()["access_token"]


async def _create_repo_for_user(user_id: str, url: str) -> str:
    async with async_session_maker() as db:
        repo = Repo(user_id=user_id, url=url, name="repo", status=RepoStatus.READY)
        db.add(repo)
        await db.commit()
        return str(repo.id)


@pytest.mark.asyncio
async def test_create_list_conversations_and_empty_message_history():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        me_resp = await client.get("/api/v1/auth/me", headers=headers)
        user_id = me_resp.json()["id"]
        repo_id = await _create_repo_for_user(user_id, "https://github.com/example/convrepo")

        create_resp = await client.post(
            f"/api/v1/repos/{repo_id}/conversations", json={"title": "First chat"}, headers=headers
        )
        assert create_resp.status_code == 201
        conversation_id = create_resp.json()["id"]

        list_resp = await client.get(f"/api/v1/repos/{repo_id}/conversations", headers=headers)
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1
        assert list_resp.json()[0]["title"] == "First chat"

        messages_resp = await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
        assert messages_resp.status_code == 200
        assert messages_resp.json() == []


@pytest.mark.asyncio
async def test_conversation_endpoints_reject_other_users():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        owner_token = await _register_and_login(client)
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        owner_me = await client.get("/api/v1/auth/me", headers=owner_headers)
        owner_id = owner_me.json()["id"]
        repo_id = await _create_repo_for_user(owner_id, "https://github.com/example/privateconv")

        create_resp = await client.post(
            f"/api/v1/repos/{repo_id}/conversations", json={"title": "Private"}, headers=owner_headers
        )
        conversation_id = create_resp.json()["id"]

        other_token = await _register_and_login(client)
        other_headers = {"Authorization": f"Bearer {other_token}"}

        assert (await client.get(f"/api/v1/repos/{repo_id}/conversations", headers=other_headers)).status_code == 404
        assert (
            await client.post(f"/api/v1/repos/{repo_id}/conversations", json={"title": "x"}, headers=other_headers)
        ).status_code == 404
        assert (
            await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=other_headers)
        ).status_code == 404
