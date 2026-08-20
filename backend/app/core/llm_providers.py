import asyncio
import json
import logging
from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic
from google import genai
from google.genai import types as genai_types
from openai import AsyncOpenAI

from app.config import get_settings
from app.core.llm import FakeLLMClient, LLMEvent, Message, ScriptedTurn, ToolCall, ToolSpec

settings = get_settings()
logger = logging.getLogger(__name__)

# Generic, non-leaking message surfaced to SSE clients when a provider call
# fails. The real exception (which can contain auth details, request/response
# bodies, or other sensitive internals) is logged server-side via
# logger.exception() instead -- see AnthropicClient.stream_chat,
# OpenAIClient.stream_chat, and GeminiClient.stream_chat below.
_PROVIDER_ERROR_MESSAGE = "The AI provider is currently unavailable. Please try again."

# Explicit rather than relying on each SDK's implicit default, so a hung
# connection to a provider surfaces as a bounded failure instead of an
# unbounded hang.
_CLIENT_TIMEOUT_SECONDS = 60.0

# Fixed priority order used both for "which provider did the operator pick"
# (settings.llm_provider) and for get_llm_client()'s fallback below.
_FALLBACK_PROVIDER_ORDER = ("anthropic", "openai", "gemini", "groq")

# Groq's API is wire-compatible with OpenAI's chat-completions format (same
# request/response/tool-call shapes) -- it's served through the openai SDK
# pointed at Groq's base_url rather than a separate SDK/dependency.
_GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Retry/backoff/timeout policy for establishing a Groq stream specifically
# (not the other providers -- Groq is the one seeing transient connect
# failures in practice). 3 attempts total, each capped at 15s, with 1s/2s
# exponential backoff between attempts -- bounded at roughly 15s+1s+15s+2s+15s
# = ~48s worst case before falling back to the standard clean error event.
_GROQ_CONNECT_TIMEOUT_SECONDS = 15.0
_GROQ_MAX_ATTEMPTS = 3
_GROQ_BACKOFF_BASE_SECONDS = 1.0


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
        self._client = AsyncAnthropic(api_key=api_key, timeout=_CLIENT_TIMEOUT_SECONDS)
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
        self._client = AsyncOpenAI(api_key=api_key, timeout=_CLIENT_TIMEOUT_SECONDS)
        self._model = model

    # Split out so a subclass (see GroqClient below) can wrap just the
    # stream-establishment step in its own retry/backoff/timeout policy,
    # without duplicating the token-consumption loop below. This step is
    # the only safe place to retry: once the caller starts iterating the
    # returned stream, some tokens may already be on their way to the user
    # -- retrying at that point would risk yielding duplicated output.
    async def _get_stream(self, openai_messages: list[dict], openai_tools: list[dict]):
        return await self._client.chat.completions.create(
            model=self._model, messages=openai_messages, tools=openai_tools, stream=True,
        )

    async def stream_chat(
        self, messages: list[Message], tools: list[ToolSpec], system_prompt: str
    ) -> AsyncIterator[LLMEvent]:
        openai_messages = [{"role": "system", "content": system_prompt}, *_to_openai_messages(messages)]
        openai_tools = [
            {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
            for t in tools
        ]

        try:
            stream = await self._get_stream(openai_messages, openai_tools)

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


class GroqClient(OpenAIClient):
    def __init__(self, api_key: str, model: str, fallback_model: str | None = None):
        # Deliberately does not call super().__init__(): that constructs an
        # AsyncOpenAI client with no base_url override (real OpenAI). Groq
        # needs its own base_url but the exact same message/tool-call
        # translation and streaming logic, so this subclass only overrides
        # client construction and inherits stream_chat unchanged.
        self._client = AsyncOpenAI(api_key=api_key, base_url=_GROQ_BASE_URL, timeout=_CLIENT_TIMEOUT_SECONDS)
        self._model = model
        self._fallback_model = fallback_model
        self._switched_to_fallback = False

    async def _get_stream(self, openai_messages: list[dict], openai_tools: list[dict]):
        # Retries only the stream-establishment call (see the base class'
        # _get_stream docstring for why that's the only safe point) with
        # exponential backoff, each attempt bounded by its own 15s cap so a
        # hung connection attempt can't silently eat the whole request
        # budget across retries.
        last_exc: Exception | None = None
        for attempt in range(_GROQ_MAX_ATTEMPTS):
            if attempt > 0:
                backoff = _GROQ_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "GroqClient: retrying stream connect (attempt %d/%d, model=%s) after %.1fs backoff",
                    attempt + 1, _GROQ_MAX_ATTEMPTS, self._model, backoff,
                )
                await asyncio.sleep(backoff)
            try:
                return await asyncio.wait_for(
                    super()._get_stream(openai_messages, openai_tools),
                    timeout=_GROQ_CONNECT_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                last_exc = exc
                # A 404/"model not found" (openai.NotFoundError) means the
                # configured model id has been retired or renamed on Groq's
                # side -- retrying the SAME model, with or without backoff,
                # will 404 every time. Switch once to the configured
                # fallback model and retry immediately (still within the
                # same attempt budget), rather than burning every remaining
                # attempt on a model that can never succeed.
                is_not_found = getattr(exc, "status_code", None) == 404 or type(exc).__name__ == "NotFoundError"
                if is_not_found and self._fallback_model and not self._switched_to_fallback:
                    logger.warning(
                        "GroqClient: model=%s not found on Groq (likely retired) -- "
                        "switching to fallback model=%s",
                        self._model, self._fallback_model,
                    )
                    self._model = self._fallback_model
                    self._switched_to_fallback = True
        assert last_exc is not None
        raise last_exc


def _to_gemini_contents(
    messages: list[Message], thought_signatures: dict[str, bytes] | None = None
) -> list[genai_types.Content]:
    # Gemini's function-calling protocol has no call id -- a function_response
    # is matched to its function_call by NAME. Build a lookup from every
    # ToolCall's id (our own bookkeeping identifier, meaningless to Gemini)
    # to its name, so a "tool" role message (which only carries a
    # tool_call_id) can be translated correctly.
    call_id_to_name: dict[str, str] = {tc.id: tc.name for msg in messages for tc in msg.tool_calls}

    result: list[genai_types.Content] = []
    for msg in messages:
        if msg.role == "user":
            result.append(genai_types.Content(role="user", parts=[genai_types.Part.from_text(text=msg.content)]))
        elif msg.role == "assistant":
            parts: list[genai_types.Part] = []
            if msg.content:
                parts.append(genai_types.Part.from_text(text=msg.content))
            for tc in msg.tool_calls:
                part = genai_types.Part.from_function_call(name=tc.name, args=tc.arguments)
                # Gemini 3's function-calling protocol requires echoing back an
                # opaque `thought_signature` alongside a replayed function_call
                # Part -- omitting it is a hard 400 INVALID_ARGUMENT on the very
                # next turn, not just a quality nit (see GeminiClient below for
                # where this is captured). `Part.from_function_call` has no
                # constructor arg for it, but Part is a plain mutable object.
                signature = (thought_signatures or {}).get(tc.id)
                if signature:
                    part.thought_signature = signature
                parts.append(part)
            result.append(genai_types.Content(role="model", parts=parts))
        elif msg.role == "tool":
            # Gemini's Content.role only accepts "user" or "model" -- there is
            # no "tool" role. A function_response Part is sent back as a
            # "user"-role Content, exactly like _to_anthropic_messages does
            # for Anthropic's tool_result blocks above.
            name = call_id_to_name.get(msg.tool_call_id or "", "")
            result.append(genai_types.Content(
                role="user",
                parts=[genai_types.Part.from_function_response(name=name, response={"result": msg.content})],
            ))
    return result


def _gemini_response_parts(chunk) -> list:
    # `chunk.function_calls` (the SDK's own convenience property) extracts
    # only `FunctionCall` objects and silently drops the sibling
    # `thought_signature` carried on the same `Part` -- so tool-calling turns
    # are read from the raw parts here instead, wherever available. Test
    # doubles that only fake `.text`/`.function_calls` (no `.candidates`)
    # simply yield no parts, which is fine: they never exercise tool calls.
    candidates = getattr(chunk, "candidates", None)
    if not candidates:
        return []
    content = getattr(candidates[0], "content", None)
    parts = getattr(content, "parts", None) if content is not None else None
    return list(parts) if parts else []


class GeminiClient:
    def __init__(self, api_key: str, model: str):
        # HttpOptions.timeout is in milliseconds, unlike the other two SDKs'
        # second-based timeout kwargs.
        self._client = genai.Client(
            api_key=api_key,
            http_options=genai_types.HttpOptions(timeout=int(_CLIENT_TIMEOUT_SECONDS * 1000)),
        )
        self._model = model
        # Cache of ToolCall.id -> thought_signature, and the counter that
        # generates those ids. Both live on the instance (not as
        # stream_chat-local state) because a `thought_signature` returned on
        # one turn must be echoed back on a later turn of the *same*
        # conversation, and app/core/agent.py's tool loop (_build_graph)
        # reuses one llm_client across every turn of one agent run. A
        # per-call-local counter would reissue "call_1" on every turn and
        # silently collide across turns in both this cache and
        # _to_gemini_contents' call_id_to_name lookup; keeping it here
        # instead guarantees ids -- and therefore cached signatures -- stay
        # unique for the life of this client.
        self._thought_signatures: dict[str, bytes] = {}
        self._call_counter = 0

    async def stream_chat(
        self, messages: list[Message], tools: list[ToolSpec], system_prompt: str
    ) -> AsyncIterator[LLMEvent]:
        gemini_tools = [
            genai_types.Tool(function_declarations=[
                genai_types.FunctionDeclaration(
                    name=t.name, description=t.description, parameters_json_schema=t.parameters
                )
                for t in tools
            ])
        ] if tools else []
        config = genai_types.GenerateContentConfig(system_instruction=system_prompt, tools=gemini_tools)

        try:
            content_parts: list[str] = []
            tool_calls: list[ToolCall] = []

            stream = await self._client.aio.models.generate_content_stream(
                model=self._model,
                contents=_to_gemini_contents(messages, self._thought_signatures),
                config=config,
            )
            async for chunk in stream:
                if chunk.text:
                    content_parts.append(chunk.text)
                    yield LLMEvent(type="token", token=chunk.text)
                for part in _gemini_response_parts(chunk):
                    fc = getattr(part, "function_call", None)
                    if fc is None:
                        continue
                    self._call_counter += 1
                    call_id = f"call_{self._call_counter}"
                    tool_calls.append(ToolCall(id=call_id, name=fc.name, arguments=dict(fc.args or {})))
                    signature = getattr(part, "thought_signature", None)
                    if signature:
                        self._thought_signatures[call_id] = signature

            if tool_calls:
                yield LLMEvent(type="tool_call", tool_calls=tool_calls)
            else:
                yield LLMEvent(type="message_done", message=Message(role="assistant", content="".join(content_parts)))
        except Exception:
            logger.exception("GeminiClient.stream_chat failed (model=%s)", self._model)
            yield LLMEvent(type="error", error=_PROVIDER_ERROR_MESSAGE)


def _provider_api_key(current_settings, provider: str) -> str | None:
    if provider == "openai":
        return current_settings.openai_api_key
    if provider == "gemini":
        return current_settings.gemini_api_key
    if provider == "groq":
        return current_settings.groq_api_key
    return current_settings.anthropic_api_key


def _build_provider_client(current_settings, provider: str):
    if provider == "openai":
        return OpenAIClient(api_key=current_settings.openai_api_key, model=current_settings.openai_model)
    if provider == "gemini":
        return GeminiClient(api_key=current_settings.gemini_api_key, model=current_settings.gemini_model)
    if provider == "groq":
        return GroqClient(
            api_key=current_settings.groq_api_key,
            model=current_settings.groq_model,
            fallback_model=current_settings.groq_fallback_model,
        )
    return AnthropicClient(api_key=current_settings.anthropic_api_key, model=current_settings.anthropic_model)


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

    # Resolution-time fallback only: try the configured provider first, then
    # the other two (in a fixed order) so a missing/invalid key on the
    # configured provider doesn't take the whole chat feature down when a
    # second provider is usable. This does NOT cover mid-stream failover --
    # each *Client.stream_chat already degrades a failure into a clean SSE
    # error event (see _PROVIDER_ERROR_MESSAGE above), and switching
    # providers mid-stream would risk duplicating partial output.
    providers_to_try = [current_settings.llm_provider] + [
        p for p in _FALLBACK_PROVIDER_ORDER if p != current_settings.llm_provider
    ]

    for provider in providers_to_try:
        if _provider_api_key(current_settings, provider):
            return _build_provider_client(current_settings, provider)

    raise RuntimeError(
        "No LLM provider is configured -- set at least one of ANTHROPIC_API_KEY, "
        "OPENAI_API_KEY, GEMINI_API_KEY, or GROQ_API_KEY."
    )
