import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import StreamWriter

from app.core.llm import LLMClient, LLMEvent, Message, ToolCall, ToolSpec

logger = logging.getLogger(__name__)

# NOTE on the LangGraph streaming API used here: the brief anticipated
# `from langgraph.config import get_stream_writer()`, a contextvar-based
# accessor added in a later LangGraph release. The pinned version in this
# project, langgraph==0.2.45, does not have `langgraph.config` at all --
# instead, `stream_mode="custom"` support works by having a node function
# declare a `writer: StreamWriter` parameter (the type lives in
# `langgraph.types`); LangGraph inspects the node's signature and injects a
# callable for that parameter by name when present. This was verified against
# the installed package source (langgraph/utils/runnable.py KWARGS_CONFIG_KEYS,
# which matches on the literal parameter name "writer") and with a standalone
# smoke test (StateGraph with a `writer: StreamWriter` node param, consumed via
# `graph.astream(state, stream_mode="custom")`) before writing this module.
# The StateGraph design itself works as designed; only the writer-acquisition
# call site moved.

# Deliberately terse -- every word here is sent on every single LLM call,
# so it's counted against the same daily/per-minute token budgets as
# history and completions (see chat.py's MAX_HISTORY_TOKENS comment for the
# quota-exhaustion context this was tightened under; ~300 tokens is this
# string's own budget). Compressed from a much more explanatory version
# (see git history) while keeping every rule that actually changed model
# behavior when it was added: the tool descriptions (needed for correct
# tool selection), the general-knowledge routing rule, the citation format,
# history-reuse, the no-repeat-call/few-calls-budget rule, and the target-
# file/section-guessing rule.
#
# The "ALWAYS set query" line earned its own sentence (not just a mention
# in read_file's tool description) after live-verifying the model doesn't
# reliably populate an optional tool parameter just because a description
# recommends it -- a real "what testing framework does this use" run called
# read_file(path="pyproject.toml") with no query at all, got a from-the-top
# truncation that never reached the [tool.pytest] section, and gave up.
# Two reinforcing fixes, not one: this imperative line, and read_file
# itself now falling back to a structural outline (see agent_tools.py's
# extract_outline) instead of a blind top truncation whenever query really
# is omitted -- so a still-unreliable query is a smaller loss than before.
SYSTEM_PROMPT = (
    "Code assistant for one GitHub repo. Tools (never guess at code you haven't seen):\n"
    "- list_directory(path): list files/dirs, empty path = root. Use first for broad questions.\n"
    "- search_code(query): find code by topic/keyword when you don't know the file.\n"
    "- read_file(path, query): file contents; query jumps to the matching section in a long file. "
    "ALWAYS set query when reading a config/manifest/CI file -- without it you get only a "
    "structural outline (section/def names), not the actual values.\n\n"
    "General software questions (concepts, comparisons, syntax, \"how does X normally work\") need "
    "no tool -- answer from knowledge. Tools are only for THIS repo's actual files/structure/behavior.\n\n"
    "For a specific thing (testing, deps, config, CI), guess the conventional file directly "
    "(pytest.ini/conftest.py/pyproject.toml, package.json/requirements.txt, README.md) instead of "
    "exploring broadly.\n\n"
    "Cite code as `path/to/file.py:12-18` (search_code result) or `path/to/file.py` (read_file). "
    "Say so if you still lack enough info -- don't speculate.\n\n"
    "Check history first -- reuse a prior tool result, never repeat an identical call. Very few tool "
    "calls available: use them precisely, then answer with what you have."
)

# Used instead of SYSTEM_PROMPT whenever search_code specifically isn't
# registered for this call (see chat.py: Settings.enable_embedding=false
# excludes it entirely, not just leaves it returning empty results -- this
# is this production deployment's actual configuration, see render.yaml).
# Live-verified against a real conversation on this exact deployment that
# leaving SYSTEM_PROMPT's search_code-describing text in place while only
# list_directory/read_file were actually registered made the model (a
# Gemini model, in this case -- confirmed the failure isn't Groq-specific)
# call search_code anyway, get back "Unknown tool: search_code", and burn
# an iteration of MAX_TOOL_ITERATIONS on a call that could never succeed --
# keep "search_code" out of this string entirely. Same compression pass as
# SYSTEM_PROMPT above.
SYSTEM_PROMPT_NO_SEARCH = (
    "Code assistant for one GitHub repo. Tools (never guess at code you haven't seen):\n"
    "- list_directory(path): list files/dirs, empty path = root. Use first for broad questions.\n"
    "- read_file(path, query): file contents; query jumps to the matching section in a long file. "
    "ALWAYS set query when reading a config/manifest/CI file -- without it you get only a "
    "structural outline (section/def names), not the actual values.\n\n"
    "General software questions (concepts, comparisons, syntax, \"how does X normally work\") need "
    "no tool -- answer from knowledge. Tools are only for THIS repo's actual files/structure/behavior.\n\n"
    "For a specific thing (testing, deps, config, CI), guess the conventional file directly "
    "(pytest.ini/conftest.py/pyproject.toml, package.json/requirements.txt, README.md) instead of "
    "exploring broadly.\n\n"
    "Cite code as `path/to/file.py` after reading it. Say so if you still lack enough info -- don't "
    "speculate.\n\n"
    "Check history first -- reuse a prior tool result, never repeat an identical call. Very few tool "
    "calls available: use them precisely, then answer with what you have."
)

# Used instead of SYSTEM_PROMPT whenever no tools are bound for this call
# (see chat.py's chitchat short-circuit, which passes tools=[] for a message
# like "ok"/"thanks"). Confirmed live: leaving the tool-describing
# SYSTEM_PROMPT in place while the actual request carried zero registered
# tools caused Groq to hard-reject the request with "APIError: Tool choice
# is none, but model called a tool" -- the model, told by the system prompt
# alone that it has three tools, attempted to call one that was never
# actually registered on this request. This prompt contains no tool-shaped
# language at all, so that contradiction can't arise. Also compressed, same
# pass as the two prompts above -- chitchat replies are the cheapest, most
# frequent call this module makes, so this string's per-token cost adds up.
SYSTEM_PROMPT_NO_TOOLS = (
    "Friendly assistant replying to a short greeting/thanks/acknowledgment, not a real code "
    "question. Respond briefly. No tools for this message -- if it's actually a real question you "
    "can't answer from context, say you'd need to look at the code rather than guessing."
)

# Deliberately tight -- every extra iteration is a full extra LLM round-trip
# plus a tool call, and both cost real latency AND real provider-quota
# tokens. This constant's history is a real tradeoff, not a one-way ratchet:
# raised 4 -> 5 after live-verifying a real multi-step question needed one
# more call than 4 allowed to conclude, then cut to 2 in a strict token-
# conservation pass after live-confirming *complete* daily-quota exhaustion
# on both configured providers (see git history for both in full). Bumped
# 2 -> 3 after live-verifying 2 was cutting it too close in practice: a
# real repo-specific question (list_directory, then read_file on a file
# that turned out not to have the answer) spent its whole 2-call budget
# without ever reaching a genuinely informative file, hitting the give-up
# message with zero calls left to try again. 3 gives one recovery call for
# exactly that "first guess was the wrong file" case while staying well
# short of the old 5/108s-worst-case-Groq-retry-era latency this was
# tightened away from. The give-up message below still fires cleanly if 3
# is too tight for a given question -- it degrades to "ask a narrower
# question" rather than hanging, and a follow-up question gets a fresh
# 3-call budget of its own.
MAX_TOOL_ITERATIONS = 3

# Hard ceiling on a single tool call (list_directory/read_file/search_code).
# These are normally fast DB-backed reads, but nothing architecturally
# prevents a slow query, an exhausted connection pool, or (for search_code)
# a slow embedding pass from stalling one -- and a stalled tool call would
# otherwise hang the whole chat turn indefinitely, since tools_node awaits
# it directly. asyncio.wait_for turns that into a bounded failure the agent
# can recover from (the timeout becomes a normal tool result, not a crash).
TOOL_TIMEOUT_SECONDS = 10.0

# Fallback text only for the (rare) case the iteration cap is hit with
# zero tool results ever gathered -- e.g. every tool call this turn failed
# outright, or the model never actually called one. See
# _synthesize_from_gathered_data below for the normal case.
_NOTHING_GATHERED_MESSAGE = (
    "I wasn't able to finish researching this within the allowed "
    "number of search steps. Could you narrow your question?"
)


def _synthesize_from_gathered_data(messages: list[Message]) -> str:
    """Best-effort, zero-token synthesis of whatever tool results were
    already gathered before MAX_TOOL_ITERATIONS was hit -- used by
    assistant_node instead of a bare apology.

    A multi-step question that exhausts the iteration budget usually still
    has real, relevant tool output sitting in `messages` (search_code hits,
    file contents, directory listings) -- the model just never got a final
    turn to synthesize an answer *from* that data. Handing that data back
    directly, with no further LLM call, costs nothing extra in tokens or
    latency and is strictly more useful than a bare apology: the citations
    (file paths/line ranges already embedded in each tool result's own
    "### path:start-end" headers -- see agent_tools.py) let the user verify
    or follow up themselves even if the assembled text isn't as polished as
    a real model-written answer would have been.

    Falls back to a plain apology only when nothing was ever gathered (see
    _NOTHING_GATHERED_MESSAGE) -- that's no worse than the old behavior for
    the case this can't improve on.
    """
    tool_messages = [m for m in messages if m.role == "tool" and m.content.strip()]
    if not tool_messages:
        return _NOTHING_GATHERED_MESSAGE

    parts = [
        "I ran out of search steps before I could fully answer, but here's what I found while "
        "researching this:"
    ]
    parts.extend(m.content.strip() for m in tool_messages)
    parts.append(
        "That's everything I was able to gather -- let me know if you'd like me to dig into one of "
        "these further, or try a narrower follow-up question."
    )
    return "\n\n".join(parts)


ToolFn = Callable[[dict], Awaitable[str]]


class AgentState(TypedDict):
    messages: list[Message]
    iterations: int
    done: bool


def _build_graph(llm_client: LLMClient, tools: list[ToolSpec], tool_functions: dict[str, ToolFn]):
    tool_names = {t.name for t in tools}
    if not tools:
        system_prompt = SYSTEM_PROMPT_NO_TOOLS
    elif "search_code" in tool_names:
        system_prompt = SYSTEM_PROMPT
    else:
        system_prompt = SYSTEM_PROMPT_NO_SEARCH

    async def assistant_node(state: AgentState, writer: StreamWriter) -> dict:
        if state["iterations"] >= MAX_TOOL_ITERATIONS:
            message = Message(role="assistant", content=_synthesize_from_gathered_data(state["messages"]))
            writer(LLMEvent(type="message_done", message=message))
            return {"messages": [*state["messages"], message], "done": True}

        tool_calls: list[ToolCall] = []
        final_message: Message | None = None
        errored = False
        accumulated_text = ""

        async for event in llm_client.stream_chat(
            state["messages"], tools=tools, system_prompt=system_prompt
        ):
            writer(event)
            if event.type == "token":
                accumulated_text += event.token or ""
            elif event.type == "tool_call":
                tool_calls = event.tool_calls or []
            elif event.type == "message_done":
                final_message = event.message
            elif event.type == "error":
                errored = True

        if errored:
            return {"done": True}
        if tool_calls:
            # A turn can carry preamble text (e.g. "Let me search for that...")
            # before the tool call. Preserve it as the message content instead
            # of hardcoding "" -- otherwise it's streamed to the user via token
            # events but never recorded in history, and both provider message
            # converters skip empty-content assistant messages entirely, so the
            # model loses all memory of what it just said on the next turn.
            return {
                "messages": [
                    *state["messages"],
                    Message(role="assistant", content=accumulated_text, tool_calls=tool_calls),
                ],
                "iterations": state["iterations"] + 1,
            }
        if final_message is not None:
            return {"messages": [*state["messages"], final_message], "done": True}
        return {"done": True}

    async def tools_node(state: AgentState, writer: StreamWriter) -> dict:
        last_message = state["messages"][-1]
        new_messages = list(state["messages"])
        for tool_call in last_message.tool_calls:
            tool_fn = tool_functions.get(tool_call.name)
            if tool_fn is None:
                result_text = f"Unknown tool: {tool_call.name}"
            else:
                try:
                    result_text = await asyncio.wait_for(tool_fn(tool_call.arguments), timeout=TOOL_TIMEOUT_SECONDS)
                except asyncio.TimeoutError:
                    logger.warning(
                        "%s tool call timed out after %.0fs for arguments=%r",
                        tool_call.name, TOOL_TIMEOUT_SECONDS, tool_call.arguments,
                    )
                    result_text = (
                        f"{tool_call.name} timed out after {TOOL_TIMEOUT_SECONDS:.0f}s -- "
                        "try a narrower request."
                    )
                except Exception:
                    logger.exception(
                        "%s tool call failed for arguments=%r", tool_call.name, tool_call.arguments
                    )
                    result_text = f"{tool_call.name} failed -- unable to complete this operation right now."
            writer(LLMEvent(type="tool_result", tool_calls=[tool_call], tool_result_text=result_text))
            new_messages.append(Message(role="tool", content=result_text, tool_call_id=tool_call.id))
        return {"messages": new_messages}

    def route_after_assistant(state: AgentState) -> str:
        if state.get("done"):
            return END
        last_message = state["messages"][-1]
        if last_message.role == "assistant" and last_message.tool_calls:
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("assistant", assistant_node)
    graph.add_node("tools", tools_node)
    graph.set_entry_point("assistant")
    graph.add_conditional_edges("assistant", route_after_assistant, {"tools": "tools", END: END})
    graph.add_edge("tools", "assistant")
    return graph.compile()


async def run_agent(
    llm_client: LLMClient,
    tools: list[ToolSpec],
    tool_functions: dict[str, ToolFn],
    messages: list[Message],
) -> AsyncIterator[LLMEvent]:
    graph = _build_graph(llm_client, tools, tool_functions)
    initial_state: AgentState = {"messages": messages, "iterations": 0, "done": False}
    async for event in graph.astream(initial_state, stream_mode="custom"):
        yield event
