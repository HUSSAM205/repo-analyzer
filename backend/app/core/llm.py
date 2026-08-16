from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None


@dataclass
class LLMEvent:
    type: Literal["token", "tool_call", "tool_result", "message_done", "error"]
    token: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_result_text: str | None = None
    message: Message | None = None
    error: str | None = None


class LLMClient(Protocol):
    def stream_chat(
        self, messages: list[Message], tools: list[ToolSpec], system_prompt: str
    ) -> AsyncIterator[LLMEvent]: ...


@dataclass
class ScriptedTurn:
    tool_calls: list[ToolCall] | None = None
    text: str | None = None


class FakeLLMClient:
    """Deterministic LLMClient for tests. Each call to stream_chat() consumes
    exactly one scripted turn, in order. Never makes a network call."""

    def __init__(self, turns: list[ScriptedTurn]):
        self._turns = list(turns)

    async def stream_chat(
        self, messages: list[Message], tools: list[ToolSpec], system_prompt: str
    ) -> AsyncIterator[LLMEvent]:
        if not self._turns:
            raise RuntimeError("FakeLLMClient ran out of scripted turns")
        turn = self._turns.pop(0)

        if turn.tool_calls:
            yield LLMEvent(type="tool_call", tool_calls=turn.tool_calls)
            return

        text = turn.text or ""
        for word in text.split(" "):
            yield LLMEvent(type="token", token=word + " ")
        yield LLMEvent(type="message_done", message=Message(role="assistant", content=text))
