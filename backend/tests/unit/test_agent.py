import asyncio

import pytest

from app.core import agent as agent_module
from app.core.agent import SYSTEM_PROMPT, SYSTEM_PROMPT_NO_SEARCH, SYSTEM_PROMPT_NO_TOOLS, run_agent
from app.core.agent_tools import LIST_DIRECTORY_TOOL_SPEC, READ_FILE_TOOL_SPEC, SEARCH_CODE_TOOL_SPEC
from app.core.llm import FakeLLMClient, Message, ScriptedTurn, ToolCall

_SEARCH_TOOLS = [SEARCH_CODE_TOOL_SPEC]
_NO_SEARCH_TOOLS = [LIST_DIRECTORY_TOOL_SPEC, READ_FILE_TOOL_SPEC]


async def _no_op_list_directory(args: dict) -> str:
    return "no files"


async def _no_op_read_file(args: dict) -> str:
    return "no content"


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


class _SystemPromptRecordingClient(FakeLLMClient):
    """FakeLLMClient that records the `system_prompt` it was called with,
    so a test can assert on exactly what the agent sent."""

    def __init__(self, turns):
        super().__init__(turns)
        self.seen_system_prompts: list[str] = []

    async def stream_chat(self, messages, tools, system_prompt):
        self.seen_system_prompts.append(system_prompt)
        async for event in super().stream_chat(messages, tools, system_prompt):
            yield event


@pytest.mark.asyncio
async def test_run_agent_uses_the_tool_describing_prompt_when_tools_are_bound():
    client = _SystemPromptRecordingClient(turns=[ScriptedTurn(text="ok")])

    events = [event async for event in run_agent(client, _SEARCH_TOOLS, {"search_code": _no_op_search}, [Message(role="user", content="hi")])]

    assert events[-1].type == "message_done"
    assert client.seen_system_prompts == [SYSTEM_PROMPT]


@pytest.mark.asyncio
async def test_run_agent_uses_the_tools_free_prompt_when_no_tools_are_bound():
    # Regression test, confirmed live: leaving the tool-describing
    # SYSTEM_PROMPT in place while the actual request carried zero
    # registered tools (see chat.py's chitchat short-circuit, which passes
    # tools=[]) caused Groq to hard-reject the request with "APIError: Tool
    # choice is none, but model called a tool" -- the model, told by the
    # system prompt alone that it had tools, tried to call one that was
    # never actually registered on the request.
    client = _SystemPromptRecordingClient(turns=[ScriptedTurn(text="You're welcome!")])

    events = [event async for event in run_agent(client, [], {}, [Message(role="user", content="thanks")])]

    assert events[-1].type == "message_done"
    assert client.seen_system_prompts == [SYSTEM_PROMPT_NO_TOOLS]
    assert SYSTEM_PROMPT_NO_TOOLS != SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_run_agent_uses_the_no_search_prompt_when_search_code_is_not_bound():
    # Regression test, confirmed live: with embedding disabled (see
    # Settings.enable_embedding -- this production deployment's actual
    # config), chat.py registers only list_directory/read_file, not
    # search_code -- but SYSTEM_PROMPT's text unconditionally describes all
    # three tools regardless of which ones are actually bound. A real model
    # (Gemini, in the live repro) called search_code anyway, got back
    # "Unknown tool: search_code", and burned a MAX_TOOL_ITERATIONS slot on
    # a call that could never succeed. SYSTEM_PROMPT_NO_SEARCH must be used
    # whenever search_code specifically is missing, even though other tools
    # are bound (the existing SYSTEM_PROMPT_NO_TOOLS only covers the
    # zero-tools case).
    client = _SystemPromptRecordingClient(turns=[ScriptedTurn(text="ok")])

    events = [
        event
        async for event in run_agent(
            client, _NO_SEARCH_TOOLS,
            {"list_directory": _no_op_list_directory, "read_file": _no_op_read_file},
            [Message(role="user", content="what does this repo do")],
        )
    ]

    assert events[-1].type == "message_done"
    assert client.seen_system_prompts == [SYSTEM_PROMPT_NO_SEARCH]
    assert "search_code" not in SYSTEM_PROMPT_NO_SEARCH
    assert SYSTEM_PROMPT_NO_SEARCH not in (SYSTEM_PROMPT, SYSTEM_PROMPT_NO_TOOLS)


@pytest.mark.asyncio
async def test_run_agent_switches_back_to_the_tool_prompt_after_a_no_tools_turn():
    # A single run_agent() call always has a fixed `tools` list for its
    # whole lifetime (chat.py decides once per turn), but this guards
    # against a future regression where the prompt choice might get
    # "stuck" from a previous turn/call rather than freshly evaluated.
    client = _SystemPromptRecordingClient(turns=[ScriptedTurn(text="ok")])
    async for _ in run_agent(client, [], {}, [Message(role="user", content="thanks")]):
        pass
    assert client.seen_system_prompts == [SYSTEM_PROMPT_NO_TOOLS]

    client2 = _SystemPromptRecordingClient(turns=[ScriptedTurn(text="ok")])
    async for _ in run_agent(client2, _SEARCH_TOOLS, {"search_code": _no_op_search}, [Message(role="user", content="how does auth work")]):
        pass
    assert client2.seen_system_prompts == [SYSTEM_PROMPT]


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
    # Both calls are requested in the SAME turn (tools_node dispatches every
    # ToolCall in one assistant message together, in one iteration) rather
    # than across two separate turns -- with MAX_TOOL_ITERATIONS now 2, two
    # tool-call turns plus a final-answer turn would need 3 rounds of
    # budget, more than this deliberately tight ceiling allows. Parallel
    # tool calls in one turn is also how a real model would typically ask
    # for two independent lookups at once, not a test-only contrivance.
    list_call = ToolCall(id="call_1", name="list_directory", arguments={"path": ""})
    read_call = ToolCall(id="call_2", name="read_file", arguments={"path": "README.md"})
    client = FakeLLMClient(
        turns=[
            ScriptedTurn(tool_calls=[list_call, read_call]),
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
async def test_run_agent_times_out_a_hanging_tool_call_instead_of_hanging_forever(monkeypatch):
    # A tool call that never returns (a stalled DB query, an exhausted
    # connection pool, ...) must not hang the whole chat turn -- tools_node
    # awaits it under asyncio.wait_for(TOOL_TIMEOUT_SECONDS). Patched to a
    # tiny value so this test doesn't actually wait 10 real seconds.
    monkeypatch.setattr(agent_module, "TOOL_TIMEOUT_SECONDS", 0.05)

    tool_call = ToolCall(id="call_1", name="search_code", arguments={"query": "auth"})
    client = FakeLLMClient(
        turns=[
            ScriptedTurn(tool_calls=[tool_call]),
            ScriptedTurn(text="Here's what I found anyway."),
        ]
    )

    async def hanging_search(args: dict) -> str:
        await asyncio.sleep(10)
        return "unreachable"

    events = [
        event
        async for event in run_agent(
            client, _SEARCH_TOOLS, {"search_code": hanging_search}, [Message(role="user", content="how does auth work")]
        )
    ]

    tool_result_events = [e for e in events if e.type == "tool_result"]
    assert len(tool_result_events) == 1
    assert "timed out" in tool_result_events[0].tool_result_text
    assert events[-1].type == "message_done"
    assert events[-1].message.content == "Here's what I found anyway."


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


@pytest.mark.asyncio
async def test_run_agent_synthesizes_from_gathered_tool_results_after_max_iterations():
    # The give-up path must not be a bare apology when real tool output was
    # actually gathered along the way -- it should hand that data back
    # directly (see agent.py's _synthesize_from_gathered_data) rather than
    # discarding it and telling the user to ask again.
    async def real_search(args: dict) -> str:
        return f"### app/auth.py:10-20 (login)\n```\ndef login(): ...\n```"

    turns = [ScriptedTurn(tool_calls=[ToolCall(id=f"call_{i}", name="search_code", arguments={"query": "auth"})]) for i in range(10)]
    client = FakeLLMClient(turns=turns)

    events = [
        event
        async for event in run_agent(client, _SEARCH_TOOLS, {"search_code": real_search}, [Message(role="user", content="how does auth work")])
    ]

    final = events[-1]
    assert final.type == "message_done"
    assert "ran out of search steps" in final.message.content
    assert "app/auth.py:10-20" in final.message.content
    assert "def login()" in final.message.content
    # Must not be the old bare-apology text -- real gathered data was found.
    assert "Could you narrow your question?" not in final.message.content


@pytest.mark.asyncio
async def test_run_agent_falls_back_to_apology_when_nothing_was_gathered():
    # If every tool call this turn came back empty (or the model never
    # produced usable results), there's nothing to synthesize from --
    # this must degrade to the plain apology, not an empty/blank message.
    async def empty_search(args: dict) -> str:
        return "   "  # whitespace-only -- counts as "nothing gathered"

    turns = [ScriptedTurn(tool_calls=[ToolCall(id=f"call_{i}", name="search_code", arguments={"query": "x"})]) for i in range(10)]
    client = FakeLLMClient(turns=turns)

    events = [
        event
        async for event in run_agent(client, _SEARCH_TOOLS, {"search_code": empty_search}, [Message(role="user", content="loop forever")])
    ]

    final = events[-1]
    assert final.type == "message_done"
    assert "Could you narrow your question?" in final.message.content
