import pytest

from app.core.agent import run_agent
from app.core.llm import FakeLLMClient, Message, ScriptedTurn, ToolCall


async def _no_op_search(query: str) -> str:
    return f"no results for {query}"


@pytest.mark.asyncio
async def test_run_agent_streams_tokens_and_terminates_on_message_done():
    client = FakeLLMClient(turns=[ScriptedTurn(text="The answer is 42")])
    events = [
        event async for event in run_agent(client, _no_op_search, [Message(role="user", content="what is the answer")])
    ]

    assert any(e.type == "token" for e in events)
    assert events[-1].type == "message_done"
    assert events[-1].message.content == "The answer is 42"


@pytest.mark.asyncio
async def test_run_agent_executes_tool_call_then_continues():
    tool_call = ToolCall(id="call_1", name="search_code", arguments={"query": "auth"})
    client = FakeLLMClient(
        turns=[
            ScriptedTurn(tool_calls=[tool_call]),
            ScriptedTurn(text="Found it in auth.py"),
        ]
    )

    captured_queries = []

    async def search_fn(query: str) -> str:
        captured_queries.append(query)
        return "auth.py:1-5 has the login function"

    events = [event async for event in run_agent(client, search_fn, [Message(role="user", content="how does auth work")])]

    assert captured_queries == ["auth"]
    event_types = [e.type for e in events]
    assert "tool_call" in event_types
    assert "tool_result" in event_types
    assert event_types[-1] == "message_done"
    assert events[-1].message.content == "Found it in auth.py"


@pytest.mark.asyncio
async def test_run_agent_propagates_llm_error():
    from app.core.llm import LLMEvent

    class ErroringClient:
        async def stream_chat(self, messages, tools, system_prompt):
            yield LLMEvent(type="error", error="rate limited")

    events = [event async for event in run_agent(ErroringClient(), _no_op_search, [Message(role="user", content="hi")])]
    assert events[-1].type == "error"
    assert events[-1].error == "rate limited"


class _RecordingLLMClient(FakeLLMClient):
    """FakeLLMClient that records the `messages` list it was called with on
    each stream_chat() invocation, so a test can inspect exactly what the
    agent loop persisted into conversation state between turns."""

    def __init__(self, turns):
        super().__init__(turns)
        self.seen_messages: list[list[Message]] = []

    async def stream_chat(self, messages, tools, system_prompt):
        self.seen_messages.append(messages)
        async for event in super().stream_chat(messages, tools, system_prompt):
            yield event


@pytest.mark.asyncio
async def test_run_agent_preserves_preamble_text_on_tool_call_turn():
    # Real providers commonly emit preamble text ("Let me search for that...")
    # before a tool call in the same turn. That text must be preserved as the
    # content of the assistant message recorded in conversation state -- not
    # hardcoded to "" -- otherwise the model loses memory of what it just said
    # on the next turn (and both provider message converters skip
    # empty-content assistant messages entirely).
    tool_call = ToolCall(id="call_1", name="search_code", arguments={"query": "auth"})
    client = _RecordingLLMClient(
        turns=[
            ScriptedTurn(text="Let me search for that.", tool_calls=[tool_call]),
            ScriptedTurn(text="Found it in auth.py"),
        ]
    )

    async def search_fn(query: str) -> str:
        return "auth.py:1-5 has the login function"

    events = [
        event
        async for event in run_agent(client, search_fn, [Message(role="user", content="how does auth work")])
    ]

    assert events[-1].type == "message_done"

    # The second stream_chat() call is the one made after the tool call --
    # its `messages` argument is exactly what the agent persisted into state,
    # which must include the preamble text, not an empty string.
    assert len(client.seen_messages) == 2
    messages_on_second_call = client.seen_messages[1]
    assistant_message_with_tool_call = next(m for m in messages_on_second_call if m.tool_calls)
    # FakeLLMClient's word-by-word tokenizer appends a trailing space to each
    # token, so strip() before comparing -- that whitespace detail is an
    # artifact of the fake, not something this test cares about.
    assert assistant_message_with_tool_call.content.strip() == "Let me search for that."


@pytest.mark.asyncio
async def test_run_agent_gives_up_gracefully_after_max_iterations():
    # Every turn is a tool call, forever -- the agent should stop after
    # MAX_TOOL_ITERATIONS rounds with a real message_done, not hang or crash.
    turns = [ScriptedTurn(tool_calls=[ToolCall(id=f"call_{i}", name="search_code", arguments={"query": "x"})]) for i in range(10)]
    client = FakeLLMClient(turns=turns)

    events = [event async for event in run_agent(client, _no_op_search, [Message(role="user", content="loop forever")])]

    assert events[-1].type == "message_done"
    assert events[-1].message.content  # some explanatory text, not empty
