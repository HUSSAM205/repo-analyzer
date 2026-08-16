import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import Message as DbMessage
from app.db.models import MessageRole, Repo, RepoStatus
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
async def test_send_message_persists_preamble_text_from_earlier_tool_call_turn(monkeypatch):
    # Regression test for the streamed-vs-persisted divergence: a turn can
    # stream preamble text ("Let me look into...") before a tool call, and
    # that text must survive into the persisted assistant message even
    # though it came from an earlier turn than the one whose message_done
    # event actually triggers the DB write.
    from app.core.llm import FakeLLMClient, ScriptedTurn, ToolCall

    async def fake_search_code(db, repo_id, query):
        return "auth.py:1-5 has the login function"

    monkeypatch.setattr("app.api.routes.chat.search_code", fake_search_code)

    tool_call = ToolCall(id="call_1", name="search_code", arguments={"query": "auth"})
    monkeypatch.setattr(
        "app.api.routes.chat.get_llm_client",
        lambda: FakeLLMClient(
            turns=[
                ScriptedTurn(text="Let me look into the auth code for you.", tool_calls=[tool_call]),
                ScriptedTurn(text="The login function lives in auth.py."),
            ]
        ),
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
            json={"content": "how does auth work?"},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            raw = ""
            async for chunk in response.aiter_text():
                raw += chunk

        events = _parse_sse_events(raw)
        assert events[-1]["type"] == "done"

        messages_resp = await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
        messages = messages_resp.json()
        assert len(messages) == 2
        persisted_content = messages[1]["content"]
        assert "Let me look into the auth code for you." in persisted_content
        assert "The login function lives in auth.py." in persisted_content


@pytest.mark.asyncio
async def test_send_message_truncates_history_to_max_history_messages(monkeypatch):
    # Regression test for the unbounded-history bug: once a conversation has
    # more than MAX_HISTORY_MESSAGES prior messages, only the most recent
    # window should be passed to the agent, in chronological order.
    from app.api.routes import chat as chat_module
    from app.core.llm import LLMEvent
    from app.core.llm import Message as AgentMessage

    captured_calls: list[list[AgentMessage]] = []

    async def fake_run_agent(llm_client, search_fn, messages):
        captured_calls.append(messages)
        yield LLMEvent(type="message_done", message=AgentMessage(role="assistant", content="ok"))

    monkeypatch.setattr(chat_module, "run_agent", fake_run_agent)
    monkeypatch.setattr(chat_module, "get_llm_client", lambda: object())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        repo_id = await _create_repo(user_id)

        conv_resp = await client.post(f"/api/v1/repos/{repo_id}/conversations", json={"title": "Chat"}, headers=headers)
        conversation_id = conv_resp.json()["id"]

        total_prior_messages = chat_module.MAX_HISTORY_MESSAGES + 10
        base_time = datetime.now(timezone.utc) - timedelta(minutes=total_prior_messages)
        async with async_session_maker() as db:
            for i in range(total_prior_messages):
                role = MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT
                db.add(
                    DbMessage(
                        conversation_id=uuid.UUID(conversation_id),
                        role=role,
                        content=f"history-message-{i}",
                        created_at=base_time + timedelta(minutes=i),
                    )
                )
            await db.commit()

        async with client.stream(
            "POST",
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "newest question"},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            async for _ in response.aiter_text():
                pass

        assert len(captured_calls) == 1
        sent_messages = captured_calls[0]
        # MAX_HISTORY_MESSAGES prior messages (truncated) + the just-sent user message.
        assert len(sent_messages) == chat_module.MAX_HISTORY_MESSAGES + 1
        contents = [m.content for m in sent_messages]

        assert "history-message-0" not in contents
        assert f"history-message-{total_prior_messages - 1}" in contents
        assert contents[-1] == "newest question"

        # The surviving window must be the most recent MAX_HISTORY_MESSAGES,
        # still in chronological (oldest-to-newest) order.
        expected_tail = [
            f"history-message-{i}"
            for i in range(total_prior_messages - chat_module.MAX_HISTORY_MESSAGES, total_prior_messages)
        ]
        assert contents[:-1] == expected_tail


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
