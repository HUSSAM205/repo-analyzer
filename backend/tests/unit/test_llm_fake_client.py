import pytest

from app.core.llm import FakeLLMClient, Message, ScriptedTurn, ToolCall, ToolSpec


@pytest.mark.asyncio
async def test_fake_client_streams_tokens_then_message_done():
    client = FakeLLMClient(turns=[ScriptedTurn(text="Hello world")])
    events = [
        event
        async for event in client.stream_chat(
            messages=[Message(role="user", content="hi")], tools=[], system_prompt="sys"
        )
    ]

    token_events = [e for e in events if e.type == "token"]
    assert "".join(e.token for e in token_events) == "Hello world "
    assert events[-1].type == "message_done"
    assert events[-1].message.content == "Hello world"


@pytest.mark.asyncio
async def test_fake_client_yields_tool_call_turn():
    tool_call = ToolCall(id="call_1", name="search_code", arguments={"query": "auth logic"})
    client = FakeLLMClient(turns=[ScriptedTurn(tool_calls=[tool_call])])

    events = [
        event
        async for event in client.stream_chat(messages=[Message(role="user", content="hi")], tools=[], system_prompt="sys")
    ]

    assert len(events) == 1
    assert events[0].type == "tool_call"
    assert events[0].tool_calls == [tool_call]


@pytest.mark.asyncio
async def test_fake_client_consumes_turns_in_order():
    client = FakeLLMClient(turns=[ScriptedTurn(text="first"), ScriptedTurn(text="second")])

    first_events = [e async for e in client.stream_chat(messages=[], tools=[], system_prompt="sys")]
    second_events = [e async for e in client.stream_chat(messages=[], tools=[], system_prompt="sys")]

    assert first_events[-1].message.content == "first"
    assert second_events[-1].message.content == "second"


@pytest.mark.asyncio
async def test_fake_client_raises_when_turns_exhausted():
    client = FakeLLMClient(turns=[])
    with pytest.raises(RuntimeError):
        async for _ in client.stream_chat(messages=[], tools=[], system_prompt="sys"):
            pass


def test_tool_spec_is_a_plain_dataclass():
    spec = ToolSpec(name="search_code", description="desc", parameters={"type": "object"})
    assert spec.name == "search_code"
