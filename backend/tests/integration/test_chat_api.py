import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import Repo, RepoStatus
from app.db.session import async_session_maker
from app.main import app

pytestmark = pytest.mark.integration


async def _register_and_login(client: AsyncClient) -> tuple[str, str]:
    email = f"chat-{uuid.uuid4()}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
    login_resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
    token = login_resp.json()["access_token"]
    me_resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return token, me_resp.json()["id"]


async def _create_repo(user_id: str) -> str:
    async with async_session_maker() as db:
        repo = Repo(user_id=user_id, url=f"https://github.com/example/chatrepo-{uuid.uuid4()}", name="chatrepo", status=RepoStatus.READY)
        db.add(repo)
        await db.commit()
        return str(repo.id)


def _parse_sse_events(raw_text: str) -> list[dict]:
    events = []
    for block in raw_text.strip().split("\n\n"):
        if not block.strip():
            continue
        lines = block.strip().split("\n")
        event_type = lines[0].removeprefix("event: ")
        import json as _json

        data = _json.loads(lines[1].removeprefix("data: "))
        events.append({"type": event_type, "data": data})
    return events


@pytest.mark.asyncio
async def test_send_message_streams_response_and_persists_messages(monkeypatch):
    from app.core.llm import FakeLLMClient, ScriptedTurn

    monkeypatch.setattr(
        "app.api.routes.chat.get_llm_client",
        lambda: FakeLLMClient(turns=[ScriptedTurn(text="The repo looks fine.")]),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        repo_id = await _create_repo(user_id)

        conv_resp = await client.post(f"/api/v1/repos/{repo_id}/conversations", json={"title": "Chat"}, headers=headers)
        conversation_id = conv_resp.json()["id"]

        async with client.stream(
            "POST",
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "Is the repo healthy?"},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            raw = ""
            async for chunk in response.aiter_text():
                raw += chunk

        events = _parse_sse_events(raw)
        assert any(e["type"] == "token" for e in events)
        assert events[-1]["type"] == "done"

        messages_resp = await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
        messages = messages_resp.json()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Is the repo healthy?"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "The repo looks fine."


@pytest.mark.asyncio
async def test_send_message_surfaces_llm_error_as_sse_error_event(monkeypatch):
    from app.core.llm import LLMEvent

    class ErroringClient:
        async def stream_chat(self, messages, tools, system_prompt):
            yield LLMEvent(type="error", error="upstream LLM API is down")

    monkeypatch.setattr("app.api.routes.chat.get_llm_client", lambda: ErroringClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        repo_id = await _create_repo(user_id)
        conv_resp = await client.post(f"/api/v1/repos/{repo_id}/conversations", json={"title": "Chat"}, headers=headers)
        conversation_id = conv_resp.json()["id"]

        async with client.stream(
            "POST",
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "hello"},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            raw = ""
            async for chunk in response.aiter_text():
                raw += chunk

        events = _parse_sse_events(raw)
        assert events[-1]["type"] == "error"
        assert "upstream LLM API is down" in events[-1]["data"]["message"]

        # The user's message is still persisted even though the assistant failed.
        messages_resp = await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
        messages = messages_resp.json()
        assert len(messages) == 1
        assert messages[0]["role"] == "user"


@pytest.mark.asyncio
async def test_send_message_rejects_other_users_conversation(monkeypatch):
    from app.core.llm import FakeLLMClient, ScriptedTurn

    monkeypatch.setattr(
        "app.api.routes.chat.get_llm_client", lambda: FakeLLMClient(turns=[ScriptedTurn(text="hi")])
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        owner_token, owner_id = await _register_and_login(client)
        repo_id = await _create_repo(owner_id)
        conv_resp = await client.post(
            f"/api/v1/repos/{repo_id}/conversations", json={"title": "Chat"}, headers={"Authorization": f"Bearer {owner_token}"}
        )
        conversation_id = conv_resp.json()["id"]

        other_token, _ = await _register_and_login(client)
        resp = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "hi"},
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 404
