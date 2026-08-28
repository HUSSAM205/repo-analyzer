import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import Conversation, MessageRole, Repo, RepoStatus
from app.db.models import Message as DbMessage
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
        # A ":"-prefixed line is an SSE comment (see chat.py's
        # _SSE_HEARTBEAT) -- no event/data fields, deliberately ignored by
        # real SSE clients. Skip it here the same way, rather than trying
        # to parse it as a real event.
        if block.strip().startswith(":"):
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
async def test_send_message_degrades_gracefully_instead_of_surfacing_llm_error(monkeypatch):
    # Regression coverage for the "3rd-turn crash": once GroqClient's own
    # internal fallback chain is exhausted (primary model -> fallback model
    # -> optional local Ollama), the assistant must still respond with a
    # normal "done" turn instead of a raw SSE "error" event -- see
    # chat.py's _graceful_degraded_reply/_persist_and_emit_degraded_reply.
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
        assert not any(e["type"] == "error" for e in events)
        assert events[-1]["type"] == "done"
        # No domain_briefing was set on this repo, so the generic (not
        # briefing-derived) degraded reply is the one that must appear --
        # see test_send_message_degrades_gracefully_using_cached_domain_briefing
        # below for the richer, briefing-derived variant.
        assert any(e["type"] == "token" and "unable to reach the AI provider" in e["data"]["text"] for e in events)

        # Both the user's message AND a degraded assistant reply are persisted
        # -- unlike the old raw-error path, the turn completes normally.
        messages_resp = await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
        messages = messages_resp.json()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        assert "unable to reach the AI provider" in messages[1]["content"]


@pytest.mark.asyncio
async def test_send_message_degrades_gracefully_using_cached_domain_briefing(monkeypatch):
    # When a domain_briefing is already cached for the repo (the normal case
    # -- generated at analysis time), the degraded reply should use it
    # instead of the generic fallback, so a rate-limited user still gets
    # something concrete about their repo.
    from app.core.llm import LLMEvent

    class ErroringClient:
        async def stream_chat(self, messages, tools, system_prompt):
            yield LLMEvent(type="error", error="rate limited (429)")

    monkeypatch.setattr("app.api.routes.chat.get_llm_client", lambda: ErroringClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        repo_id = await _create_repo(user_id)

        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            repo.domain_briefing = {
                "primary_field": "Web SaaS",
                "target_audience": "Backend engineers.",
                "architecture_overview": "A FastAPI backend talks to a Postgres database.",
            }
            await db.commit()

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
        assert not any(e["type"] == "error" for e in events)
        assert events[-1]["type"] == "done"

        messages_resp = await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
        messages = messages_resp.json()
        assert len(messages) == 2
        assert "FastAPI backend talks to a Postgres database" in messages[1]["content"]


@pytest.mark.asyncio
async def test_send_message_prefers_deterministic_keyword_match_over_generic_briefing(monkeypatch):
    # Tier 3 of the degrade chain (deterministic_answer.py) runs before the
    # generic/briefing-based reply -- when the question's keywords actually
    # match something in the indexed repo, that's a more useful answer than
    # a generic "here's the architecture overview" message, even though
    # both are available.
    from app.core.llm import LLMEvent
    from app.db.models import File

    class ErroringClient:
        async def stream_chat(self, messages, tools, system_prompt):
            yield LLMEvent(type="error", error="rate limited (429)")

    monkeypatch.setattr("app.api.routes.chat.get_llm_client", lambda: ErroringClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        repo_id = await _create_repo(user_id)

        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            repo.domain_briefing = {
                "primary_field": "Web SaaS",
                "target_audience": "Backend engineers.",
                "architecture_overview": "A FastAPI backend talks to a Postgres database.",
            }
            db.add(File(repo_id=uuid.UUID(repo_id), path="app/auth/login.py", content="def login(): pass"))
            await db.commit()

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
        assert not any(e["type"] == "error" for e in events)
        assert events[-1]["type"] == "done"

        messages_resp = await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
        messages = messages_resp.json()
        assert "app/auth/login.py" in messages[1]["content"]
        assert "FastAPI backend talks to a Postgres database" not in messages[1]["content"]


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
async def test_send_message_truncates_history_to_rolling_window_messages(monkeypatch):
    # Regression test for the unbounded-history bug: once a conversation has
    # more than ROLLING_WINDOW_MESSAGES prior messages, only the most recent
    # window should be passed to the agent, in chronological order.
    from app.api.routes import chat as chat_module
    from app.core.llm import LLMEvent
    from app.core.llm import Message as AgentMessage

    captured_calls: list[list[AgentMessage]] = []

    async def fake_run_agent(llm_client, tools, tool_functions, messages):
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

        total_prior_messages = chat_module.ROLLING_WINDOW_MESSAGES + 10
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
        # ROLLING_WINDOW_MESSAGES prior messages (truncated) + the just-sent user message.
        assert len(sent_messages) == chat_module.ROLLING_WINDOW_MESSAGES + 1
        contents = [m.content for m in sent_messages]

        assert "history-message-0" not in contents
        assert f"history-message-{total_prior_messages - 1}" in contents
        assert contents[-1] == "newest question"

        # The surviving window must be the most recent ROLLING_WINDOW_MESSAGES,
        # still in chronological (oldest-to-newest) order.
        expected_tail = [
            f"history-message-{i}"
            for i in range(total_prior_messages - chat_module.ROLLING_WINDOW_MESSAGES, total_prior_messages)
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
    # window of exactly ROLLING_WINDOW_MESSAGES rows would start on an
    # assistant message, and assert the leading assistant message(s) get
    # dropped so the window handed to the agent always starts with "user".
    from app.api.routes import chat as chat_module
    from app.core.llm import LLMEvent
    from app.core.llm import Message as AgentMessage

    captured_calls: list[list[AgentMessage]] = []

    async def fake_run_agent(llm_client, tools, tool_functions, messages):
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
        # reproduces the same numerical effect: ROLLING_WINDOW_MESSAGES is even
        # (40), so picking an odd total makes the tail window's start index
        # (total - ROLLING_WINDOW_MESSAGES) odd too, i.e. an ASSISTANT message,
        # exactly the case a naive count-based window mishandles.
        total_prior_messages = chat_module.ROLLING_WINDOW_MESSAGES + 11  # odd total
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
        # the most recent ROLLING_WINDOW_MESSAGES rows really would start with
        # an assistant message, so this test is actually exercising the fix
        # rather than trivially passing.
        naive_window_start_index = total_prior_messages - chat_module.ROLLING_WINDOW_MESSAGES
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

    async def fake_run_agent(llm_client, tools, tool_functions, messages):
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
        # Regression: the text was previously only ever persisted to the DB
        # for this no-preceding-tokens case, never actually streamed to the
        # live client -- a viewer watching the turn happen saw an empty
        # bubble and then "done", with the real text only appearing on a
        # later reload. A live viewer must see the same text that gets
        # persisted, in a "token" event, before "done".
        token_events = [e for e in events if e["type"] == "token"]
        assert token_events
        assert "".join(e["data"]["text"] for e in token_events) == give_up_text

        messages_resp = await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
        messages = messages_resp.json()
        assert len(messages) == 2
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == give_up_text


@pytest.mark.asyncio
async def test_send_message_never_persists_a_blank_assistant_reply(monkeypatch):
    # Regression test, confirmed live: a model can end a turn with no tool
    # calls, no streamed tokens, AND an empty event.message.content -- e.g.
    # gpt-oss-20b's entire response was reasoning wrapped in
    # <think>...</think> with nothing after it, which _ThinkTagFilter (see
    # llm_providers.py) correctly strips, leaving nothing behind. Persisting
    # "" and reporting "done" anyway left a silent, unexplained blank
    # assistant turn. A short fallback message must be persisted instead.
    from app.api.routes import chat as chat_module
    from app.core.llm import LLMEvent
    from app.core.llm import Message as AgentMessage

    async def fake_run_agent(llm_client, tools, tool_functions, messages):
        # No "token" events, and event.message.content is also empty --
        # distinct from the give-up path above, which always carries real
        # explanatory text in event.message.content.
        yield LLMEvent(type="message_done", message=AgentMessage(role="assistant", content=""))

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
            json={"content": "how does the signer verify a token?"},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            raw = ""
            async for chunk in response.aiter_text():
                raw += chunk

        events = _parse_sse_events(raw)
        assert events[-1]["type"] == "done"
        token_events = [e for e in events if e["type"] == "token"]
        assert token_events
        streamed_text = "".join(e["data"]["text"] for e in token_events)
        assert "rephrasing" in streamed_text.lower()

        messages_resp = await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
        messages = messages_resp.json()
        assert len(messages) == 2
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"]  # not empty
        assert "rephrasing" in messages[1]["content"].lower()
        assert messages[1]["content"] == streamed_text


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
async def test_send_message_excludes_search_code_tool_when_embedding_disabled(monkeypatch):
    # Confirmed live: loading the real CodeBERT model during analysis's
    # embedding step is what exceeds a free-tier 512MB instance's memory
    # (see app/workers/tasks.py). Settings.enable_embedding=false means
    # nothing ever populates the vector index, so search_code must not be
    # offered to the agent at all -- list_directory/read_file remain
    # available and still give it full access to every file.
    from app.api.routes import chat as chat_module
    from app.core.llm import LLMEvent
    from app.core.llm import Message as AgentMessage

    captured_tool_names: list[str] = []

    async def fake_run_agent(llm_client, tools, tool_functions, messages):
        captured_tool_names.extend(t.name for t in tools)
        assert set(tool_functions.keys()) == set(captured_tool_names)
        yield LLMEvent(type="message_done", message=AgentMessage(role="assistant", content="ok"))

    monkeypatch.setattr(chat_module, "run_agent", fake_run_agent)
    monkeypatch.setattr(chat_module, "get_llm_client", lambda: object())
    monkeypatch.setattr(chat_module.settings, "enable_embedding", False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        repo_id = await _create_repo(user_id)

        conv_resp = await client.post(f"/api/v1/repos/{repo_id}/conversations", json={"title": "Chat"}, headers=headers)
        conversation_id = conv_resp.json()["id"]

        # Not "hi" -- that's now a chitchat message (see
        # test_send_message_skips_tools_for_chitchat below), which would
        # exercise the wrong code path for what this test is actually about
        # (tool composition based on Settings.enable_embedding).
        async with client.stream(
            "POST",
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "explain the repository architecture"},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            async for _ in response.aiter_text():
                pass

        assert "search_code" not in captured_tool_names
        assert set(captured_tool_names) == {"list_directory", "read_file"}


@pytest.mark.asyncio
async def test_send_message_emits_sse_heartbeats_during_a_slow_agent_turn(monkeypatch):
    # A slow tool call or LLM round-trip must not leave the SSE stream
    # producing zero bytes for a long stretch -- a proxy/browser could
    # treat that as a dead connection and drop it before the real answer
    # ever arrives. Simulates "slow" with a real agent stand-in that sleeps
    # well past a (patched-down) heartbeat interval before its one real
    # event, so this test runs in well under a second rather than actually
    # waiting out the real 15s production interval.
    from app.api.routes import chat as chat_module
    from app.core.llm import LLMEvent
    from app.core.llm import Message as AgentMessage

    monkeypatch.setattr(chat_module, "_HEARTBEAT_INTERVAL_SECONDS", 0.05)

    async def slow_fake_run_agent(llm_client, tools, tool_functions, messages):
        await asyncio.sleep(0.3)
        yield LLMEvent(type="message_done", message=AgentMessage(role="assistant", content="ok"))

    monkeypatch.setattr(chat_module, "run_agent", slow_fake_run_agent)
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
            json={"content": "explain the repository architecture"},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            raw = ""
            async for chunk in response.aiter_text():
                raw += chunk

    assert raw.count(": keep-alive") >= 2
    events = _parse_sse_events(raw)
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_send_message_includes_search_code_tool_when_embedding_enabled(monkeypatch):
    from app.api.routes import chat as chat_module
    from app.core.llm import LLMEvent
    from app.core.llm import Message as AgentMessage

    captured_tool_names: list[str] = []

    async def fake_run_agent(llm_client, tools, tool_functions, messages):
        captured_tool_names.extend(t.name for t in tools)
        yield LLMEvent(type="message_done", message=AgentMessage(role="assistant", content="ok"))

    monkeypatch.setattr(chat_module, "run_agent", fake_run_agent)
    monkeypatch.setattr(chat_module, "get_llm_client", lambda: object())
    monkeypatch.setattr(chat_module.settings, "enable_embedding", True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        repo_id = await _create_repo(user_id)

        conv_resp = await client.post(f"/api/v1/repos/{repo_id}/conversations", json={"title": "Chat"}, headers=headers)
        conversation_id = conv_resp.json()["id"]

        # Not "hi" -- see the comment in the disabled-embedding test above.
        async with client.stream(
            "POST",
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "explain the repository architecture"},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            async for _ in response.aiter_text():
                pass

        assert set(captured_tool_names) == {"search_code", "list_directory", "read_file"}


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["ok", "Thanks!", "  waiting  ", "Got it.", "hi"])
async def test_send_message_skips_tools_for_chitchat(monkeypatch, content):
    # A short conversational reply never needs a repository lookup -- no
    # tools should even be offered to the model, regardless of
    # Settings.enable_embedding.
    from app.api.routes import chat as chat_module
    from app.core.llm import LLMEvent
    from app.core.llm import Message as AgentMessage

    captured_tool_specs: list = []
    captured_tool_functions: dict = {}

    async def fake_run_agent(llm_client, tools, tool_functions, messages):
        captured_tool_specs.extend(tools)
        captured_tool_functions.update(tool_functions)
        yield LLMEvent(type="message_done", message=AgentMessage(role="assistant", content="You're welcome!"))

    monkeypatch.setattr(chat_module, "run_agent", fake_run_agent)
    monkeypatch.setattr(chat_module, "get_llm_client", lambda: object())
    monkeypatch.setattr(chat_module.settings, "enable_embedding", True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        repo_id = await _create_repo(user_id)

        conv_resp = await client.post(f"/api/v1/repos/{repo_id}/conversations", json={"title": "Chat"}, headers=headers)
        conversation_id = conv_resp.json()["id"]

        async with client.stream(
            "POST",
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": content},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            async for _ in response.aiter_text():
                pass

        assert captured_tool_specs == []
        assert captured_tool_functions == {}


@pytest.mark.asyncio
async def test_send_message_does_not_treat_a_real_question_as_chitchat(monkeypatch):
    # Guards against an overly broad chitchat matcher: a real question that
    # happens to start with a word from the chitchat list ("ok") must still
    # get full tool access.
    from app.api.routes import chat as chat_module
    from app.core.llm import LLMEvent
    from app.core.llm import Message as AgentMessage

    captured_tool_names: list[str] = []

    async def fake_run_agent(llm_client, tools, tool_functions, messages):
        captured_tool_names.extend(t.name for t in tools)
        yield LLMEvent(type="message_done", message=AgentMessage(role="assistant", content="Sure, looking..."))

    monkeypatch.setattr(chat_module, "run_agent", fake_run_agent)
    monkeypatch.setattr(chat_module, "get_llm_client", lambda: object())
    monkeypatch.setattr(chat_module.settings, "enable_embedding", True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        repo_id = await _create_repo(user_id)

        conv_resp = await client.post(f"/api/v1/repos/{repo_id}/conversations", json={"title": "Chat"}, headers=headers)
        conversation_id = conv_resp.json()["id"]

        async with client.stream(
            "POST",
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "ok but what does auth.py actually do"},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            async for _ in response.aiter_text():
                pass

        assert set(captured_tool_names) == {"search_code", "list_directory", "read_file"}


@pytest.mark.asyncio
async def test_send_message_derives_a_title_from_the_first_message(monkeypatch):
    from app.core.llm import FakeLLMClient, ScriptedTurn

    monkeypatch.setattr(
        "app.api.routes.chat.get_llm_client",
        lambda: FakeLLMClient(turns=[ScriptedTurn(text="An answer.")]),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        repo_id = await _create_repo(user_id)

        conv_resp = await client.post(f"/api/v1/repos/{repo_id}/conversations", json={"title": "New conversation"}, headers=headers)
        conversation_id = conv_resp.json()["id"]
        assert conv_resp.json()["title"] == "New conversation"

        async with client.stream(
            "POST",
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "How does the auth middleware work in this repo?"},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            async for _ in response.aiter_text():
                pass

        list_resp = await client.get(f"/api/v1/repos/{repo_id}/conversations", headers=headers)
        [conv] = [c for c in list_resp.json() if c["id"] == conversation_id]
        assert conv["title"] == "How does the auth middleware work in this repo?"


@pytest.mark.asyncio
async def test_send_message_does_not_rename_a_conversation_past_its_first_message(monkeypatch):
    from app.core.llm import FakeLLMClient, ScriptedTurn

    monkeypatch.setattr(
        "app.api.routes.chat.get_llm_client",
        lambda: FakeLLMClient(turns=[ScriptedTurn(text="ok")]),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        repo_id = await _create_repo(user_id)

        conv_resp = await client.post(f"/api/v1/repos/{repo_id}/conversations", json={"title": "New conversation"}, headers=headers)
        conversation_id = conv_resp.json()["id"]

        for content in ["first message sets the title", "second message must not override it"]:
            monkeypatch.setattr(
                "app.api.routes.chat.get_llm_client",
                lambda: FakeLLMClient(turns=[ScriptedTurn(text="ok")]),
            )
            async with client.stream(
                "POST",
                f"/api/v1/conversations/{conversation_id}/messages",
                json={"content": content},
                headers=headers,
            ) as response:
                assert response.status_code == 200
                async for _ in response.aiter_text():
                    pass

        list_resp = await client.get(f"/api/v1/repos/{repo_id}/conversations", headers=headers)
        [conv] = [c for c in list_resp.json() if c["id"] == conversation_id]
        assert conv["title"] == "first message sets the title"


@pytest.mark.asyncio
async def test_send_message_injects_conversation_summary_as_context(monkeypatch):
    # Regression coverage for the rolling-window architecture: a
    # conversation with an existing summary must have it injected ahead of
    # the recent-messages window, not silently dropped.
    from app.api.routes import chat as chat_module
    from app.core.llm import LLMEvent
    from app.core.llm import Message as AgentMessage

    captured_calls: list[list[AgentMessage]] = []

    async def fake_run_agent(llm_client, tools, tool_functions, messages):
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

        async with async_session_maker() as db:
            conversation = await db.get(Conversation, uuid.UUID(conversation_id))
            conversation.summary = "The user is building a FastAPI + Next.js repo analyzer."
            conversation.summary_covers_through_message_count = 4
            await db.commit()

        async with client.stream(
            "POST",
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "what did we say the stack was?"},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            async for _ in response.aiter_text():
                pass

        assert len(captured_calls) == 1
        sent_messages = captured_calls[0]
        assert any(
            "FastAPI + Next.js repo analyzer" in m.content for m in sent_messages if m.role == "assistant"
        )
        assert sent_messages[0].role == "user"
        assert sent_messages[-1].content == "what did we say the stack was?"


@pytest.mark.asyncio
async def test_send_message_background_task_extends_conversation_summary_once_window_exceeded(monkeypatch):
    from app.api.routes import chat as chat_module
    from app.core.llm import FakeLLMClient, ScriptedTurn

    monkeypatch.setattr(
        chat_module, "get_llm_client", lambda: FakeLLMClient(turns=[ScriptedTurn(text="An answer.")])
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        repo_id = await _create_repo(user_id)

        conv_resp = await client.post(f"/api/v1/repos/{repo_id}/conversations", json={"title": "Chat"}, headers=headers)
        conversation_id = conv_resp.json()["id"]

        # Seed exactly ROLLING_WINDOW_MESSAGES prior messages -- after this
        # turn adds one more user+assistant pair, the total (WINDOW + 2)
        # exceeds the window by 2, so the oldest 2 seeded messages should
        # get folded into the summary.
        base_time = datetime.now(timezone.utc) - timedelta(minutes=chat_module.ROLLING_WINDOW_MESSAGES)
        async with async_session_maker() as db:
            for i in range(chat_module.ROLLING_WINDOW_MESSAGES):
                role = MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT
                db.add(DbMessage(
                    conversation_id=uuid.UUID(conversation_id), role=role,
                    content=f"seed-{i}", created_at=base_time + timedelta(minutes=i),
                ))
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

        async with async_session_maker() as db:
            conversation = await db.get(Conversation, uuid.UUID(conversation_id))
            assert conversation.summary == "An answer."
            assert conversation.summary_covers_through_message_count == 2


@pytest.mark.asyncio
async def test_send_message_rate_limited_after_capacity(monkeypatch):
    from app.api.routes import chat as chat_module
    from app.core.llm import FakeLLMClient, ScriptedTurn

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        repo_id = await _create_repo(user_id)
        conv_resp = await client.post(f"/api/v1/repos/{repo_id}/conversations", json={"title": "Chat"}, headers=headers)
        conversation_id = conv_resp.json()["id"]

        # Chat's bucket capacity (see config.py's rate_limit_chat_bucket_capacity)
        # is deliberately sized well above a normal multi-turn conversation --
        # exceed it by a comfortable margin rather than hardcoding a specific
        # request count, so this test stays correct if that capacity changes.
        from app.core.rate_limit import settings as rate_limit_settings

        request_count = rate_limit_settings.rate_limit_chat_bucket_capacity + 5

        last_status = None
        for _ in range(request_count):
            monkeypatch.setattr(
                chat_module, "get_llm_client", lambda: FakeLLMClient(turns=[ScriptedTurn(text="ok")])
            )
            resp = await client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                json={"content": "hi"},
                headers=headers,
            )
            last_status = resp.status_code
        assert last_status == 429


@pytest.mark.asyncio
async def test_15_turn_conversation_survives_persistent_rate_limiting(monkeypatch):
    # End-to-end regression test for the reported "3rd-turn crash": a
    # conversation that runs long enough for the LLM provider to start
    # failing (simulated here from turn 3 onward, matching the bug report)
    # must never surface a raw SSE "error" event to the client and must
    # never 5xx/raise -- every one of the 15 turns should complete with a
    # normal "done" event, whether from a real answer or a graceful
    # degraded reply. Also exercises the raised chat rate-limit bucket
    # (config.py's rate_limit_chat_bucket_capacity): 15 rapid-fire turns
    # must not themselves trip the *application's own* 429, which the old
    # capacity=5 bucket would have done well before turn 15.
    from app.api.routes import chat as chat_module
    from app.core.llm import LLMEvent
    from app.core.llm import Message as AgentMessage

    class SometimesRateLimitedClient:
        """The first 2 calls answer normally; every call after that
        simulates GroqClient having exhausted its own primary+fallback
        model chain (a persistent 429), exactly like the bug report."""

        def __init__(self):
            self.calls = 0

        async def stream_chat(self, messages, tools, system_prompt):
            self.calls += 1
            if self.calls <= 2:
                yield LLMEvent(
                    type="message_done",
                    message=AgentMessage(role="assistant", content=f"Real answer #{self.calls}."),
                )
            else:
                yield LLMEvent(type="error", error="rate limited (429) on both primary and fallback model")

    client_double = SometimesRateLimitedClient()
    monkeypatch.setattr(chat_module, "get_llm_client", lambda: client_double)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        repo_id = await _create_repo(user_id)

        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            repo.domain_briefing = {
                "primary_field": "Web SaaS",
                "target_audience": "Backend engineers.",
                "architecture_overview": "A FastAPI backend talks to a Postgres database.",
            }
            await db.commit()

        conv_resp = await client.post(f"/api/v1/repos/{repo_id}/conversations", json={"title": "Chat"}, headers=headers)
        conversation_id = conv_resp.json()["id"]

        TURN_COUNT = 15
        for turn in range(1, TURN_COUNT + 1):
            async with client.stream(
                "POST",
                f"/api/v1/conversations/{conversation_id}/messages",
                json={"content": f"question number {turn}"},
                headers=headers,
            ) as response:
                assert response.status_code == 200, f"turn {turn} returned HTTP {response.status_code}"
                raw = ""
                async for chunk in response.aiter_text():
                    raw += chunk

            events = _parse_sse_events(raw)
            assert not any(e["type"] == "error" for e in events), f"turn {turn} surfaced a raw error event"
            assert events[-1]["type"] == "done", f"turn {turn} did not end in a done event"

        messages_resp = await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
        messages = messages_resp.json()
        assert len(messages) == TURN_COUNT * 2
        assert all(m["content"] for m in messages), "no message should ever persist as blank"
        # Turns 3-15 all hit the simulated persistent rate limit and must
        # have used the briefing-derived degraded reply, not a raw error.
        degraded_replies = [m for m in messages if "FastAPI backend talks to a Postgres database" in m["content"]]
        assert len(degraded_replies) == TURN_COUNT - 2
