import pytest

from app.core.conversation_summary import fold_into_summary
from app.core.llm import FakeLLMClient, LLMEvent, Message, ScriptedTurn


@pytest.mark.asyncio
async def test_returns_existing_summary_unchanged_when_no_new_messages():
    client = FakeLLMClient(turns=[])  # would raise if called -- must not be
    result = await fold_into_summary(client, "prior summary", [])
    assert result == "prior summary"


@pytest.mark.asyncio
async def test_folds_new_messages_into_the_summary():
    client = FakeLLMClient(turns=[ScriptedTurn(text="Updated summary text.")])
    messages = [
        Message(role="user", content="How does auth work?"),
        Message(role="assistant", content="It uses JWT tokens."),
    ]

    result = await fold_into_summary(client, "User asked about the repo structure.", messages)

    assert result == "Updated summary text."


@pytest.mark.asyncio
async def test_first_update_with_no_prior_summary_still_works():
    client = FakeLLMClient(turns=[ScriptedTurn(text="First summary.")])
    messages = [Message(role="user", content="hi")]

    result = await fold_into_summary(client, None, messages)

    assert result == "First summary."


@pytest.mark.asyncio
async def test_keeps_previous_summary_on_llm_error_event():
    class ErroringClient:
        async def stream_chat(self, messages, tools, system_prompt):
            yield LLMEvent(type="error", error="rate limited")

    result = await fold_into_summary(ErroringClient(), "prior summary", [Message(role="user", content="hi")])

    assert result == "prior summary"


@pytest.mark.asyncio
async def test_keeps_previous_summary_when_llm_raises():
    class RaisingClient:
        async def stream_chat(self, messages, tools, system_prompt):
            raise ConnectionError("network is down")
            yield  # pragma: no cover - makes this an async generator

    result = await fold_into_summary(RaisingClient(), "prior summary", [Message(role="user", content="hi")])

    assert result == "prior summary"


@pytest.mark.asyncio
async def test_returns_none_on_failure_when_there_was_no_prior_summary():
    class RaisingClient:
        async def stream_chat(self, messages, tools, system_prompt):
            raise ConnectionError("network is down")
            yield  # pragma: no cover

    result = await fold_into_summary(RaisingClient(), None, [Message(role="user", content="hi")])

    assert result is None


@pytest.mark.asyncio
async def test_keeps_previous_summary_when_llm_returns_empty_text():
    client = FakeLLMClient(turns=[ScriptedTurn(text="")])
    result = await fold_into_summary(client, "prior summary", [Message(role="user", content="hi")])
    assert result == "prior summary"
