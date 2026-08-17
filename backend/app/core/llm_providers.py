import json
import logging
from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from app.config import get_settings
from app.core.llm import FakeLLMClient, LLMEvent, Message, ScriptedTurn, ToolCall, ToolSpec

settings = get_settings()
logger = logging.getLogger(__name__)

# Generic, non-leaking message surfaced to SSE clients when a provider call
# fails. The real exception (which can contain auth details, request/response
# bodies, or other sensitive internals) is logged server-side via
# logger.exception() instead -- see AnthropicClient.stream_chat and
# OpenAIClient.stream_chat below.
_PROVIDER_ERROR_MESSAGE = "The AI provider is currently unavailable. Please try again."


def _to_anthropic_messages(messages: list[Message]) -> list[dict]:
    result: list[dict] = []
    for msg in messages:
        if msg.role == "user":
            result.append({"role": "user", "content": msg.content})
        elif msg.role == "assistant":
            if msg.tool_calls:
                content: list[dict] = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                content.extend(
                    {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}
                    for tc in msg.tool_calls
                )
                result.append({"role": "assistant", "content": content})
            else:
                result.append({"role": "assistant", "content": msg.content})
        elif msg.role == "tool":
            result.append({
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": msg.tool_call_id, "content": msg.content}],
            })
    return result


class AnthropicClient:
    def __init__(self, api_key: str, model: str):
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def stream_chat(
        self, messages: list[Message], tools: list[ToolSpec], system_prompt: str
    ) -> AsyncIterator[LLMEvent]:
        anthropic_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools
        ]

        try:
            async with self._client.messages.stream(
                model=self._model,
                max_tokens=4096,
                system=system_prompt,
                messages=_to_anthropic_messages(messages),
                tools=anthropic_tools,
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        yield LLMEvent(type="token", token=event.delta.text)

                final_message = await stream.get_final_message()
                tool_calls = [
                    ToolCall(id=block.id, name=block.name, arguments=block.input)
                    for block in final_message.content
                    if block.type == "tool_use"
                ]
                if tool_calls:
                    yield LLMEvent(type="tool_call", tool_calls=tool_calls)
                else:
                    text = "".join(block.text for block in final_message.content if block.type == "text")
                    yield LLMEvent(type="message_done", message=Message(role="assistant", content=text))
        except Exception:
            logger.exception("AnthropicClient.stream_chat failed (model=%s)", self._model)
            yield LLMEvent(type="error", error=_PROVIDER_ERROR_MESSAGE)


def _to_openai_messages(messages: list[Message]) -> list[dict]:
    result: list[dict] = []
    for msg in messages:
        if msg.role == "user":
            result.append({"role": "user", "content": msg.content})
        elif msg.role == "assistant":
            if msg.tool_calls:
                result.append({
                    "role": "assistant",
                    "content": msg.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                        for tc in msg.tool_calls
                    ],
                })
            else:
                result.append({"role": "assistant", "content": msg.content})
        elif msg.role == "tool":
            result.append({"role": "tool", "tool_call_id": msg.tool_call_id, "content": msg.content})
    return result


class OpenAIClient:
    def __init__(self, api_key: str, model: str):
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def stream_chat(
        self, messages: list[Message], tools: list[ToolSpec], system_prompt: str
    ) -> AsyncIterator[LLMEvent]:
        openai_messages = [{"role": "system", "content": system_prompt}, *_to_openai_messages(messages)]
        openai_tools = [
            {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
            for t in tools
        ]

        try:
            stream = await self._client.chat.completions.create(
                model=self._model, messages=openai_messages, tools=openai_tools, stream=True,
            )

            content_parts: list[str] = []
            tool_call_accumulator: dict[int, dict] = {}

            async for chunk in stream:
                delta = chunk.choices[0].delta

                if delta.content:
                    content_parts.append(delta.content)
                    yield LLMEvent(type="token", token=delta.content)

                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        entry = tool_call_accumulator.setdefault(tc_delta.index, {"id": "", "name": "", "arguments": ""})
                        if tc_delta.id:
                            entry["id"] = tc_delta.id
                        if tc_delta.function and tc_delta.function.name:
                            entry["name"] = tc_delta.function.name
                        if tc_delta.function and tc_delta.function.arguments:
                            entry["arguments"] += tc_delta.function.arguments

            if tool_call_accumulator:
                tool_calls = [
                    ToolCall(id=entry["id"], name=entry["name"], arguments=json.loads(entry["arguments"] or "{}"))
                    for entry in tool_call_accumulator.values()
                ]
                yield LLMEvent(type="tool_call", tool_calls=tool_calls)
            else:
                yield LLMEvent(type="message_done", message=Message(role="assistant", content="".join(content_parts)))
        except Exception:
            logger.exception("OpenAIClient.stream_chat failed (model=%s)", self._model)
            yield LLMEvent(type="error", error=_PROVIDER_ERROR_MESSAGE)


def get_llm_client():
    current_settings = get_settings()
    if current_settings.llm_provider == "fake":
        return FakeLLMClient(
            turns=[
                ScriptedTurn(
                    text=(
                        "This is a response from the fake LLM provider, used for local development "
                        "and end-to-end testing without a real API key. I can see this repository's "
                        "code via the search_code tool, but this specific reply is scripted."
                    )
                )
            ]
        )
    if current_settings.llm_provider == "openai":
        if not current_settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured but LLM_PROVIDER=openai")
        return OpenAIClient(api_key=current_settings.openai_api_key, model=current_settings.openai_model)
    if not current_settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured but LLM_PROVIDER=anthropic")
    return AnthropicClient(api_key=current_settings.anthropic_api_key, model=current_settings.anthropic_model)
