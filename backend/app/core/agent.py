import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import StreamWriter

from app.core.agent_tools import SEARCH_CODE_TOOL_SPEC
from app.core.llm import LLMClient, LLMEvent, Message, ToolCall

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
    "repository. Use the search_code tool to find relevant code before "
    "answering -- never guess at code you haven't seen. When you reference "
    "code in your answer, always cite it as `path/to/file.py:12-18` (the "
    "file path and line range). If the search results don't contain enough "
    "information to answer confidently, say so rather than speculating."
)

MAX_TOOL_ITERATIONS = 5

SearchFn = Callable[[str], Awaitable[str]]


class AgentState(TypedDict):
    messages: list[Message]
    iterations: int
    done: bool


def _build_graph(llm_client: LLMClient, search_fn: SearchFn):
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
            state["messages"], tools=[SEARCH_CODE_TOOL_SPEC], system_prompt=SYSTEM_PROMPT
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
            if tool_call.name == "search_code":
                try:
                    result_text = await search_fn(tool_call.arguments.get("query", ""))
                except Exception:
                    logger.exception("search_code tool call failed for query=%r", tool_call.arguments.get("query"))
                    result_text = "search_code failed -- unable to search the repository right now."
            else:
                result_text = f"Unknown tool: {tool_call.name}"
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


async def run_agent(llm_client: LLMClient, search_fn: SearchFn, messages: list[Message]) -> AsyncIterator[LLMEvent]:
    graph = _build_graph(llm_client, search_fn)
    initial_state: AgentState = {"messages": messages, "iterations": 0, "done": False}
    async for event in graph.astream(initial_state, stream_mode="custom"):
        yield event
