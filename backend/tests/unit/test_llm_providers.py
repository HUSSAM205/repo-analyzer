from unittest.mock import MagicMock

import pytest

from app.core.llm import Message, ToolCall
from app.core.llm_providers import AnthropicClient, OpenAIClient, _to_anthropic_messages, _to_openai_messages


def test_to_anthropic_messages_converts_user_and_assistant():
    messages = [
        Message(role="user", content="What does main do?"),
        Message(role="assistant", content="It's the entry point."),
    ]
    result = _to_anthropic_messages(messages)
    assert result == [
        {"role": "user", "content": "What does main do?"},
        {"role": "assistant", "content": "It's the entry point."},
    ]


def test_to_anthropic_messages_converts_tool_call_and_result():
    tool_call = ToolCall(id="call_1", name="search_code", arguments={"query": "main"})
    messages = [
        Message(role="assistant", content="", tool_calls=[tool_call]),
        Message(role="tool", content="found it", tool_call_id="call_1"),
    ]
    result = _to_anthropic_messages(messages)
    assert result[0]["role"] == "assistant"
    assert result[0]["content"][0]["type"] == "tool_use"
    assert result[0]["content"][0]["id"] == "call_1"
    assert result[1]["role"] == "user"
    assert result[1]["content"][0]["type"] == "tool_result"
    assert result[1]["content"][0]["tool_use_id"] == "call_1"


def test_to_openai_messages_converts_tool_call_and_result():
    tool_call = ToolCall(id="call_1", name="search_code", arguments={"query": "main"})
    messages = [
        Message(role="assistant", content="", tool_calls=[tool_call]),
        Message(role="tool", content="found it", tool_call_id="call_1"),
    ]
    result = _to_openai_messages(messages)
    assert result[0]["role"] == "assistant"
    assert result[0]["tool_calls"][0]["id"] == "call_1"
    assert result[0]["tool_calls"][0]["function"]["name"] == "search_code"
    assert result[1] == {"role": "tool", "tool_call_id": "call_1", "content": "found it"}


# A distinctive marker planted inside a raw exception message, standing in for
# whatever sensitive detail a real provider SDK exception could carry (auth
# headers, connection strings, request/response bodies, etc). The assertions
# below check this string never reaches the LLMEvent surfaced to SSE clients.
_SECRET_MARKER = "secret_connection_string_12345"


@pytest.mark.asyncio
async def test_anthropic_client_sanitizes_provider_exception():
    client = AnthropicClient(api_key="test-key", model="test-model")
    client._client.messages.stream = MagicMock(side_effect=RuntimeError(_SECRET_MARKER))

    events = [
        event
        async for event in client.stream_chat(
            messages=[Message(role="user", content="hi")], tools=[], system_prompt="sys"
        )
    ]

    assert len(events) == 1
    assert events[0].type == "error"
    assert events[0].error is not None
    assert _SECRET_MARKER not in events[0].error


def test_get_llm_client_returns_fake_client_when_provider_is_fake(monkeypatch):
    from app.core.llm import FakeLLMClient
    from app.core.llm_providers import get_llm_client
    from app.config import get_settings

    monkeypatch.setenv("LLM_PROVIDER", "fake")
    get_settings.cache_clear()
    try:
        client = get_llm_client()
        assert isinstance(client, FakeLLMClient)
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_openai_client_sanitizes_provider_exception():
    client = OpenAIClient(api_key="test-key", model="test-model")

    async def _raise(*args, **kwargs):
        raise RuntimeError(_SECRET_MARKER)

    client._client.chat.completions.create = _raise

    events = [
        event
        async for event in client.stream_chat(
            messages=[Message(role="user", content="hi")], tools=[], system_prompt="sys"
        )
    ]

    assert len(events) == 1
    assert events[0].type == "error"
    assert events[0].error is not None
    assert _SECRET_MARKER not in events[0].error
