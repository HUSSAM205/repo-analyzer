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


def test_to_gemini_contents_converts_user_and_assistant():
    from app.core.llm_providers import _to_gemini_contents

    messages = [
        Message(role="user", content="What does main do?"),
        Message(role="assistant", content="It's the entry point."),
    ]
    result = _to_gemini_contents(messages)
    assert result[0].role == "user"
    assert result[0].parts[0].text == "What does main do?"
    assert result[1].role == "model"
    assert result[1].parts[0].text == "It's the entry point."


def test_to_gemini_contents_converts_tool_call_and_result_matched_by_name():
    from app.core.llm_providers import _to_gemini_contents

    tool_call = ToolCall(id="call_1", name="search_code", arguments={"query": "main"})
    messages = [
        Message(role="assistant", content="", tool_calls=[tool_call]),
        Message(role="tool", content="found it", tool_call_id="call_1"),
    ]
    result = _to_gemini_contents(messages)
    assert result[0].role == "model"
    assert result[0].parts[0].function_call.name == "search_code"
    assert result[1].role == "tool"
    assert result[1].parts[0].function_response.name == "search_code"


@pytest.mark.asyncio
async def test_gemini_client_streams_tokens_and_completes(monkeypatch):
    from app.core.llm_providers import GeminiClient

    class FakeChunk:
        def __init__(self, text=None, function_calls=None):
            self.text = text
            self.function_calls = function_calls

    async def fake_stream():
        yield FakeChunk(text="It's ")
        yield FakeChunk(text="the entry point.")

    class FakeModels:
        async def generate_content_stream(self, **kwargs):
            return fake_stream()

    class FakeAio:
        def __init__(self):
            self.models = FakeModels()

    client = GeminiClient(api_key="test-key", model="test-model")
    # google-genai 2.18.1's Client.aio is a read-only property (no setter),
    # so it can't be assigned on the instance like a plain attribute. Swap
    # the class-level descriptor for the duration of this test instead;
    # monkeypatch restores the real property afterward.
    monkeypatch.setattr(type(client._client), "aio", property(lambda self: FakeAio()))

    events = [
        event
        async for event in client.stream_chat(
            messages=[Message(role="user", content="What does main do?")], tools=[], system_prompt="sys"
        )
    ]

    assert [e.type for e in events] == ["token", "token", "message_done"]
    assert events[-1].message.content == "It's the entry point."


@pytest.mark.asyncio
async def test_gemini_client_sanitizes_provider_exception(monkeypatch):
    from app.core.llm_providers import GeminiClient

    client = GeminiClient(api_key="test-key", model="test-model")

    class FakeModels:
        async def generate_content_stream(self, **kwargs):
            raise RuntimeError(_SECRET_MARKER)

    class FakeAio:
        def __init__(self):
            self.models = FakeModels()

    # Same read-only-property workaround as above.
    monkeypatch.setattr(type(client._client), "aio", property(lambda self: FakeAio()))

    events = [
        event
        async for event in client.stream_chat(
            messages=[Message(role="user", content="hi")], tools=[], system_prompt="sys"
        )
    ]

    assert len(events) == 1
    assert events[0].type == "error"
    assert _SECRET_MARKER not in events[0].error


def test_get_llm_client_returns_gemini_client_when_provider_is_gemini(monkeypatch):
    from app.core.llm_providers import GeminiClient, get_llm_client
    from app.config import get_settings

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    get_settings.cache_clear()
    try:
        client = get_llm_client()
        assert isinstance(client, GeminiClient)
    finally:
        get_settings.cache_clear()


def test_get_llm_client_raises_when_gemini_key_missing(monkeypatch):
    from app.core.llm_providers import get_llm_client
    from app.config import get_settings

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    # Settings reads GEMINI_API_KEY from backend/.env (which carries a real
    # key in this environment) whenever the environment variable itself is
    # unset -- pydantic-settings falls back to the dotenv file, so plain
    # delenv wouldn't actually clear it. Setting the env var to an empty
    # string overrides the dotenv value (env vars rank above dotenv in
    # pydantic-settings' source priority) while still being falsy.
    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError):
            get_llm_client()
    finally:
        get_settings.cache_clear()


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
