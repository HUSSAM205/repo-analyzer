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

SYSTEM_PROMPT = (
    "You are a code assistant answering questions about a specific GitHub "
    "repository. You have three tools -- never guess at code or structure you "
    "haven't actually seen:\n"
    "- list_directory: see the files/subdirectories in a directory (empty "
    "path for the root). Start broad questions like 'explain the "
    "architecture' here to get an overview before digging in.\n"
    "- search_code: find code relevant to a topic or keyword when you don't "
    "already know which file it's in.\n"
    "- read_file: read one specific file in full, once you know its path "
    "(from list_directory or search_code output) and need more than a "
    "chunked snippet -- e.g. a README, config/manifest file, or a source "
    "file whose full context matters.\n"
    "For broad architectural questions, prefer list_directory first, then "
    "read_file on the files that look most load-bearing (README, entry "
    "points, config), using search_code to fill in specific gaps. When you "
    "reference code in your answer, always cite it as `path/to/file.py:12-18` "
    "(the file path and line range) for a search_code result, or just "
    "`path/to/file.py` for something you read_file'd in full. If you still "
    "don't have enough information to answer confidently, say so rather than "
    "speculating.\n\n"
    "Before calling any tool, check whether the conversation history already "
    "contains what you need -- a prior read_file/search_code/list_directory "
    "result, or content the user already showed you. A short follow-up like "
    "'summarize it', 'explain that', or 'what does this do' almost always "
    "refers to something already loaded earlier in this conversation, not a "
    "fresh, unrelated question -- answer directly from that existing context "
    "instead of re-reading the file or re-searching the repository from "
    "scratch. Only call a tool again if the history genuinely doesn't cover "
    "what's being asked, or the user is clearly pointing at something new."
)

# 5 was too tight for the more deliberate, multi-step search style of the
# model that turned out most reliable for this workload (qwen/qwen3.6-27b,
# see llm_providers.py/config.py) -- confirmed live, it was still issuing
# well-formed, evolving queries and finding real content when it hit the
# old cap, cut off before it could synthesize a final answer.
MAX_TOOL_ITERATIONS = 8

ToolFn = Callable[[dict], Awaitable[str]]


class AgentState(TypedDict):
    messages: list[Message]
    iterations: int
    done: bool


def _build_graph(llm_client: LLMClient, tools: list[ToolSpec], tool_functions: dict[str, ToolFn]):
    async def assistant_node(state: AgentState, writer: StreamWriter) -> dict:
        if state["iterations"] >= MAX_TOOL_ITERATIONS:
            message = Message(
                role="assistant",
                content=(
                    "I wasn't able to finish researching this within the allowed "
                    "number of search steps. Could you narrow your question?"
                ),
            )
            writer(LLMEvent(type="message_done", message=message))
            return {"messages": [*state["messages"], message], "done": True}

        tool_calls: list[ToolCall] = []
        final_message: Message | None = None
        errored = False
        accumulated_text = ""

        async for event in llm_client.stream_chat(
            state["messages"], tools=tools, system_prompt=SYSTEM_PROMPT
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
                    result_text = await tool_fn(tool_call.arguments)
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
