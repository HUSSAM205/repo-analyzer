import pytest

from app.core.agent import run_agent
from app.core.agent_tools import SEARCH_CODE_TOOL_SPEC
from app.core.llm import FakeLLMClient, Message, ScriptedTurn, ToolCall

_SEARCH_TOOLS = [SEARCH_CODE_TOOL_SPEC]


async def _no_op_search(args: dict) -> str:
    return f"no results for {args.get('query')}"


@pytest.mark.asyncio
async def test_run_agent_streams_tokens_and_terminates_on_message_done():
    client = FakeLLMClient(turns=[ScriptedTurn(text="The answer is 42")])
    events = [
        event
        async for event in run_agent(
            client, _SEARCH_TOOLS, {"search_code": _no_op_search}, [Message(role="user", content="what is the answer")]
        )
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

    async def search_fn(args: dict) -> str:
        captured_queries.append(args.get("query"))
        return "auth.py:1-5 has the login function"

    events = [
        event
        async for event in run_agent(
            client, _SEARCH_TOOLS, {"search_code": search_fn}, [Message(role="user", content="how does auth work")]
        )
    ]

    assert captured_queries == ["auth"]
    event_types = [e.type for e in events]
    assert "tool_call" in event_types
    assert "tool_result" in event_types
    assert event_types[-1] == "message_done"
    assert events[-1].message.content == "Found it in auth.py"


@pytest.mark.asyncio
async def test_run_agent_dispatches_to_the_matching_tool_by_name():
    # Multiple real tools now exist (search_code, list_directory, read_file)
    # -- confirm tools_node routes each ToolCall to the function registered
    # under its own name, not just whichever one happens to be first/only.
    list_call = ToolCall(id="call_1", name="list_directory", arguments={"path": ""})
    read_call = ToolCall(id="call_2", name="read_file", arguments={"path": "README.md"})
    client = FakeLLMClient(
        turns=[
            ScriptedTurn(tool_calls=[list_call]),
            ScriptedTurn(tool_calls=[read_call]),
            ScriptedTurn(text="This repo has a README."),
        ]
    )

    calls_seen = []

    async def list_directory_fn(args: dict) -> str:
        calls_seen.append(("list_directory", args))
        return "README.md\nsrc/"

    async def read_file_fn(args: dict) -> str:
        calls_seen.append(("read_file", args))
        return "### README.md\n```\n# Hello\n```"

    async def search_fn(args: dict) -> str:
        calls_seen.append(("search_code", args))
        return "unused"

    events = [
        event
        async for event in run_agent(
            client,
            [SEARCH_CODE_TOOL_SPEC],
            {"list_directory": list_directory_fn, "read_file": read_file_fn, "search_code": search_fn},
            [Message(role="user", content="explain the architecture")],
        )
    ]

    assert calls_seen == [
        ("list_directory", {"path": ""}),
        ("read_file", {"path": "README.md"}),
    ]
    assert events[-1].type == "message_done"
    assert events[-1].message.content == "This repo has a README."


@pytest.mark.asyncio
async def test_run_agent_reports_unknown_tool_without_crashing():
    # Defensive: a provider hallucinating a tool name that isn't registered
    # must not crash the whole turn -- it should be told the tool doesn't
    # exist (as a normal tool result) so it can recover on its own.
    bad_call = ToolCall(id="call_1", name="delete_repo", arguments={})
    client = FakeLLMClient(
        turns=[
            ScriptedTurn(tool_calls=[bad_call]),
            ScriptedTurn(text="I can't do that, but here's what I found instead."),
        ]
    )

    events = [
        event
        async for event in run_agent(client, _SEARCH_TOOLS, {"search_code": _no_op_search}, [Message(role="user", content="delete everything")])
    ]

    tool_result_events = [e for e in events if e.type == "tool_result"]
    assert len(tool_result_events) == 1
    assert "Unknown tool" in tool_result_events[0].tool_result_text
    assert events[-1].type == "message_done"


@pytest.mark.asyncio
async def test_run_agent_propagates_llm_error():
    from app.core.llm import LLMEvent

    class ErroringClient:
        async def stream_chat(self, messages, tools, system_prompt):
            yield LLMEvent(type="error", error="rate limited")

    events = [
        event
        async for event in run_agent(ErroringClient(), _SEARCH_TOOLS, {"search_code": _no_op_search}, [Message(role="user", content="hi")])
    ]
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

    async def search_fn(args: dict) -> str:
        return "auth.py:1-5 has the login function"

    events = [
        event
        async for event in run_agent(
            client, _SEARCH_TOOLS, {"search_code": search_fn}, [Message(role="user", content="how does auth work")]
        )
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

    events = [
        event
        async for event in run_agent(client, _SEARCH_TOOLS, {"search_code": _no_op_search}, [Message(role="user", content="loop forever")])
    ]

    assert events[-1].type == "message_done"
    assert events[-1].message.content  # some explanatory text, not empty
