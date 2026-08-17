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
async def test_send_message_history_window_never_starts_with_assistant_message(monkeypatch):
    # Regression test: a failed turn commits only the user message (the
    # error path never persists an assistant reply), which can permanently
    # shift the user/assistant alternation parity for a conversation. Once
    # that has happened, a naive count-based window can start with an
    # assistant message -- and Anthropic's Messages API rejects a request
    # whose first message isn't role "user". Build a message history where a
    # window of exactly MAX_HISTORY_MESSAGES rows would start on an
    # assistant message, and assert the leading assistant message(s) get
    # dropped so the window handed to the agent always starts with "user".
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

        # Every successful turn contributes exactly two messages (U then A),
        # so a conversation's prior-message count is even *unless* its most
        # recent turn failed and left a dangling, unanswered user message --
        # which is exactly the scenario in the bug report (a failed turn
        # permanently shifting the user/assistant alternation parity for
        # everything that follows it). Using an odd prior-message count with
        # otherwise perfect alternation (U at even index, A at odd index)
        # reproduces the same numerical effect: MAX_HISTORY_MESSAGES is even
        # (40), so picking an odd total makes the tail window's start index
        # (total - MAX_HISTORY_MESSAGES) odd too, i.e. an ASSISTANT message,
        # exactly the case a naive count-based window mishandles.
        total_prior_messages = chat_module.MAX_HISTORY_MESSAGES + 11  # odd total
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

        # Sanity check on the test's own setup: confirm a naive window of
        # the most recent MAX_HISTORY_MESSAGES rows really would start with
        # an assistant message, so this test is actually exercising the fix
        # rather than trivially passing.
        naive_window_start_index = total_prior_messages - chat_module.MAX_HISTORY_MESSAGES
        assert naive_window_start_index % 2 == 1  # odd index => ASSISTANT per the loop above

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
        assert len(sent_messages) > 0
        assert sent_messages[0].role == "user"


@pytest.mark.asyncio
async def test_send_message_persists_give_up_message_with_no_preceding_tokens(monkeypatch):
    # Regression test: the agent's max-tool-iterations give-up message (see
    # app/core/agent.py) is emitted directly via a message_done event with
    # no preceding token events at all. final_text must fall back to
    # event.message.content in that case instead of persisting empty
    # content.
    from app.api.routes import chat as chat_module
    from app.core.llm import LLMEvent
    from app.core.llm import Message as AgentMessage

    give_up_text = (
        "I wasn't able to finish researching this within the allowed number of search steps."
    )

    async def fake_run_agent(llm_client, search_fn, messages):
        # No "token" events at all -- mirrors agent.py's give-up path, which
        # writes message_done directly without streaming any tokens first.
        yield LLMEvent(type="message_done", message=AgentMessage(role="assistant", content=give_up_text))

    monkeypatch.setattr(chat_module, "run_agent", fake_run_agent)
    monkeypatch.setattr(chat_module, "get_llm_client", lambda: object())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        repo_id = await _create_repo(user_id)

        conv_resp = await client.post(f"/api/v1/repos/{repo_id}/conversations", json={"title": "Chat"}, headers=headers)
        conversation_id = conv_resp.json()["id"]

        async with client.stream(
            "POST",
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "find the thing"},
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
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == give_up_text


@pytest.mark.asyncio
async def test_send_message_accessible_by_other_users_conversation(monkeypatch):
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
        async with client.stream(
            "POST",
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "hi"},
            headers={"Authorization": f"Bearer {other_token}"},
        ) as response:
            assert response.status_code == 200
            raw = ""
            async for chunk in response.aiter_text():
                raw += chunk

        events = _parse_sse_events(raw)
        assert any(e["type"] == "token" for e in events)
        assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_send_message_rate_limited_after_capacity(monkeypatch):
    from app.core.llm import FakeLLMClient, ScriptedTurn

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        repo_id = await _create_repo(user_id)
        conv_resp = await client.post(f"/api/v1/repos/{repo_id}/conversations", json={"title": "Chat"}, headers=headers)
        conversation_id = conv_resp.json()["id"]

        last_status = None
        for _ in range(10):
            monkeypatch.setattr(
                "app.api.routes.chat.get_llm_client",
                lambda: FakeLLMClient(turns=[ScriptedTurn(text="ok")]),
            )
            resp = await client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                json={"content": "hi"},
                headers=headers,
            )
            last_status = resp.status_code
        assert last_status == 429
