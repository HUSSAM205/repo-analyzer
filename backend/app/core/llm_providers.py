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
# unbounded hang. Tightened from 60s to 8s as part of a strict-latency,
# fail-fast-to-the-next-tier pass -- with DualProviderClient available to
# fail over to a second provider immediately on any error (see below), a
# request that hasn't gotten a first byte back in 8s is far more likely
# genuinely stuck than about to succeed slowly, and every second spent
# waiting on a probably-dead connection is a second not spent trying the
# tier that might actually answer. GroqClient uses its own, separate
# _GROQ_CONNECT_TIMEOUT_SECONDS below rather than this one.
_CLIENT_TIMEOUT_SECONDS = 8.0

# OpenAI-compatible chat-completions calls (OpenAIClient/GroqClient/
# OllamaClient) previously left max_tokens unset, so the completion side of
# a request was unbounded -- on a provider with a low per-minute token
# quota (see token_budget.py's docstring: Groq TPM limits as low as 8000
# observed live), an unusually long generation could itself consume a large
# share of that budget on top of the prompt. Anthropic's/Gemini's clients
# are capped the same way, at the same value (see AnthropicClient.
# stream_chat and GeminiClient.stream_chat below). Tightened from 1024 to
# 600 as part of a strict token-conservation pass -- 600 tokens (~400-450
# words) is still a real, complete answer for a chat turn, just no longer
# generous enough to be the dominant per-request cost.
_MAX_COMPLETION_TOKENS = 600

# Fixed priority order used both for "which provider did the operator pick"
# (settings.llm_provider) and for get_llm_client()'s fallback below.
_FALLBACK_PROVIDER_ORDER = ("anthropic", "openai", "gemini", "groq")

# Groq's API is wire-compatible with OpenAI's chat-completions format (same
# request/response/tool-call shapes) -- it's served through the openai SDK
# pointed at Groq's base_url rather than a separate SDK/dependency.
_GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Retry/backoff/timeout policy for establishing a Groq stream specifically
# (not the other providers -- Groq is the one seeing transient connect
# failures in practice). History: 15s -> 25s -> 35s, each bump chasing real
# observed connect latency on tool-heavy prompts (see git history for the
# full account) -- all three values optimized purely for "give a slow-but-
# would-succeed request enough time," with no ceiling on how long that
# could take in total (~108s worst case at 35s/3 attempts).
#
# Cut sharply to 8s/2 attempts/0.25s backoff as part of a deliberate
# strategy change, not a continuation of that trend: this deployment now
# has DualProviderClient (see below) to fail over to a second, independent
# provider the moment Groq's own chain gives up -- so the right question
# stopped being "how long could a slow Groq request take" and became "how
# quickly can we abandon a struggling Groq and let Gemini have a turn."
# Worst case is now ~8s (primary) + 0.25s backoff + ~8s (fallback model) =
# ~16.25s before DualProviderClient tries Gemini, instead of ~108s of
# Groq-only retries eating the whole turn. A 429 (quota) also doesn't
# benefit from backoff at all -- the same exhausted quota is exhausted
# whether retried after 0.25s or 2s -- so the short backoff here is purely
# about not hammering a struggling connection, not about waiting out a
# rate limit (switching to the fallback *model* is what actually addresses
# that, and already happens on the very first failure, no retry needed).
_GROQ_CONNECT_TIMEOUT_SECONDS = 8.0
_GROQ_MAX_ATTEMPTS = 2
_GROQ_BACKOFF_BASE_SECONDS = 0.25

# Ollama's OpenAI-compatible endpoint, used as GroqClient's last-resort
# local fallback when the cloud provider is exhausted/unreachable (see
# GroqClient.stream_chat). `host.docker.internal` is the standard Docker
# Desktop DNS name a container uses to reach services running on the host
# -- works out of the box on Docker Desktop for Windows/Mac (this
# deployment's target); a Linux host needs an `extra_hosts` entry, added in
# docker-compose.yml for that reason.
_OLLAMA_DEFAULT_BASE_URL = "http://host.docker.internal:11434/v1"

_LOCAL_FALLBACK_UNAVAILABLE_MESSAGE = (
    "The cloud AI provider is temporarily rate-limited, and the local "
    "Ollama fallback is not reachable. Start Ollama locally (or wait for "
    "the cloud provider's quota to reset) and try again."
)


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
                max_tokens=_MAX_COMPLETION_TOKENS,
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


class _ThinkTagFilter:
    """Strips inline <think>...</think> reasoning blocks from a token stream.

    Confirmed live: openai/gpt-oss-20b on Groq (see config.py's groq_model)
    emits its chain-of-thought as literal "<think>...</think>" text mixed
    directly into the same content stream as its real answer -- unlike
    Anthropic's extended thinking (a distinct content-block type, never
    surfaced as a "token" event by AnthropicClient above) or a real OpenAI
    reasoning model (which doesn't expose raw CoT via chat-completions
    content at all). Left unfiltered, the reasoning trace streams straight
    into the chat bubble as if it were the answer.

    Safe against the tag being split across chunk boundaries: a small
    pending buffer holds back any suffix that could still become the start
    of a marker on the next chunk, at most len(marker)-1 characters --
    imperceptible in a token stream, and a no-op in steady state for any
    model that never emits these tags at all (the common case).
    """

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self):
        self._pending = ""
        self._inside = False

    def feed(self, chunk: str) -> str:
        text = self._pending + chunk
        self._pending = ""
        out: list[str] = []
        i = 0
        while i < len(text):
            marker = self._CLOSE if self._inside else self._OPEN
            idx = text.find(marker, i)
            if idx == -1:
                tail_keep = min(len(marker) - 1, len(text) - i)
                safe_end = len(text) - tail_keep
                if safe_end > i and not self._inside:
                    out.append(text[i:safe_end])
                self._pending = text[safe_end:]
                break
            if not self._inside:
                out.append(text[i:idx])
            self._inside = not self._inside
            i = idx + len(marker)
        return "".join(out)

    def flush(self) -> str:
        # Any leftover buffered text belongs to the stream's tail. Still
        # "inside" a <think> block here means the model's output was cut
        # off mid-reasoning -- dropping it is safer than leaking a
        # half-formed reasoning trace to the user.
        remaining = self._pending
        self._pending = ""
        return "" if self._inside else remaining


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
            model=self._model,
            messages=openai_messages,
            tools=openai_tools,
            stream=True,
            max_tokens=_MAX_COMPLETION_TOKENS,
        )

    async def stream_chat(
        self, messages: list[Message], tools: list[ToolSpec], system_prompt: str
    ) -> AsyncIterator[LLMEvent]:
        openai_messages = [{"role": "system", "content": system_prompt}, *_to_openai_messages(messages)]
        openai_tools = [
            {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
            for t in tools
        ]

        # Declared outside the try block (always a fresh, empty filter here)
        # so the except branch below can always safely call .flush() on it --
        # including when the failure happens before any content was ever
        # fed to it, in which case flush() is a harmless no-op.
        think_filter = _ThinkTagFilter()

        try:
            stream = await self._get_stream(openai_messages, openai_tools)

            content_parts: list[str] = []
            tool_call_accumulator: dict[int, dict] = {}

            async for chunk in stream:
                delta = chunk.choices[0].delta

                if delta.content:
                    visible = think_filter.feed(delta.content)
                    if visible:
                        content_parts.append(visible)
                        yield LLMEvent(type="token", token=visible)

                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        entry = tool_call_accumulator.setdefault(tc_delta.index, {"id": "", "name": "", "arguments": ""})
                        if tc_delta.id:
                            entry["id"] = tc_delta.id
                        if tc_delta.function and tc_delta.function.name:
                            entry["name"] = tc_delta.function.name
                        if tc_delta.function and tc_delta.function.arguments:
                            entry["arguments"] += tc_delta.function.arguments

            trailing = think_filter.flush()
            if trailing:
                content_parts.append(trailing)
                yield LLMEvent(type="token", token=trailing)

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
            # A mid-stream failure can leave real, already-arrived content
            # sitting in the filter's boundary-safety buffer (see
            # _ThinkTagFilter) -- surface it before the error event instead
            # of silently dropping up to a few trailing characters of
            # legitimate output. Still "inside" an unclosed <think> block
            # here means the dropped tail was reasoning trace, not a real
            # answer -- flush() already handles that case correctly.
            trailing = think_filter.flush()
            if trailing:
                yield LLMEvent(type="token", token=trailing)
            yield LLMEvent(type="error", error=_PROVIDER_ERROR_MESSAGE)


class OllamaClient(OpenAIClient):
    """Talks to a local Ollama server via its OpenAI-compatible endpoint.

    Used as GroqClient's last-resort local fallback (see
    GroqClient.stream_chat) -- same message/tool-call translation and
    streaming logic as any other OpenAI-compatible provider, just pointed at
    a local base_url. Ollama accepts any non-empty string as an API key (it
    doesn't check it); "ollama" is the placeholder Ollama's own docs use.
    """

    def __init__(self, model: str, base_url: str):
        self._client = AsyncOpenAI(api_key="ollama", base_url=base_url, timeout=_CLIENT_TIMEOUT_SECONDS)
        self._model = model


class GroqClient(OpenAIClient):
    def __init__(
        self,
        api_key: str,
        model: str,
        fallback_model: str | None = None,
        local_fallback_model: str | None = None,
        local_fallback_base_url: str = _OLLAMA_DEFAULT_BASE_URL,
    ):
        # Deliberately does not call super().__init__(): that constructs an
        # AsyncOpenAI client with no base_url override (real OpenAI). Groq
        # needs its own base_url but the exact same message/tool-call
        # translation and streaming logic, so this subclass only overrides
        # client construction and inherits stream_chat unchanged.
        self._client = AsyncOpenAI(api_key=api_key, base_url=_GROQ_BASE_URL, timeout=_CLIENT_TIMEOUT_SECONDS)
        self._model = model
        self._fallback_model = fallback_model
        self._switched_to_fallback = False
        # None disables the local fallback entirely (e.g. an environment
        # with no Ollama server) -- see get_llm_client()/config.py.
        self._local_fallback_model = local_fallback_model
        self._local_fallback_base_url = local_fallback_base_url

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
                # will 404 every time. A 429/"rate limit" (openai.
                # RateLimitError) most often means Groq's per-model *daily*
                # token quota is exhausted (confirmed live: "tokens per day
                # (TPD): Limit 200000, Used 199399... try again in 27m58s")
                # -- backoff measured in seconds can't fix a quota that
                # resets in tens of minutes. A 503 (openai.
                # InternalServerError -- Groq's own model/endpoint is
                # temporarily overloaded or unavailable) is the same story:
                # it's a property of that specific model's current
                # capacity, not a transient network blip. A 400 (openai.
                # BadRequestError) is more of a grab-bag -- sometimes a
                # genuinely malformed request (switching models won't help,
                # but see below), sometimes a model-specific validation
                # failure like a context-length limit only *this* model
                # hits, which a different model's larger context window can
                # genuinely resolve. In every one of these four cases,
                # retrying the same model would just burn the rest of the
                # attempt budget on a request that's guaranteed to fail
                # again -- switch once to the configured fallback model and
                # retry immediately (still within the same attempt budget)
                # instead. Worst case (a truly malformed request that fails
                # identically on the fallback model too) is no worse than
                # not switching at all: the attempt budget still exhausts
                # cleanly into the same "provider unavailable" SSE error
                # event rather than a hang or a crash -- switching on 400
                # never makes the failure mode worse, only sometimes better.
                is_not_found = getattr(exc, "status_code", None) == 404 or type(exc).__name__ == "NotFoundError"
                is_rate_limited = getattr(exc, "status_code", None) == 429 or type(exc).__name__ == "RateLimitError"
                is_unavailable = getattr(exc, "status_code", None) == 503
                is_bad_request = getattr(exc, "status_code", None) == 400 or type(exc).__name__ == "BadRequestError"
                if (
                    (is_not_found or is_rate_limited or is_unavailable or is_bad_request)
                    and self._fallback_model
                    and not self._switched_to_fallback
                ):
                    if is_not_found:
                        reason = "not found on Groq (likely retired)"
                    elif is_rate_limited:
                        reason = "rate-limited (daily token quota likely exhausted)"
                    elif is_unavailable:
                        reason = "unavailable (Groq returned 503 -- likely temporarily overloaded)"
                    else:
                        reason = "rejected the request (Groq returned 400 -- possibly a model-specific limit)"
                    logger.warning(
                        "GroqClient: model=%s %s -- switching to fallback model=%s",
                        self._model, reason, self._fallback_model,
                    )
                    self._model = self._fallback_model
                    self._switched_to_fallback = True
        assert last_exc is not None
        raise last_exc

    async def stream_chat(
        self, messages: list[Message], tools: list[ToolSpec], system_prompt: str
    ) -> AsyncIterator[LLMEvent]:
        # The cloud attempt first, exactly as before (including the
        # connect-retry/model-switch logic in _get_stream above).
        # OpenAIClient.stream_chat never raises -- it catches everything
        # internally and yields an "error" event instead -- so failure here
        # is detected by watching for that event, not by catching an
        # exception.
        cloud_failed = False
        yielded_real_content = False
        async for event in super().stream_chat(messages, tools, system_prompt):
            if event.type == "error":
                cloud_failed = True
                break
            if event.type in ("token", "tool_call"):
                yielded_real_content = True
            yield event

        if not cloud_failed:
            return

        # Once real content has already reached the caller, failing over to
        # a different provider now would risk a duplicated or inconsistent
        # answer -- the same reason the connect-retry above only ever
        # retries the pre-stream connect step, never a mid-stream failure.
        # Surface the plain error instead in that case, or when no local
        # fallback is configured at all.
        if yielded_real_content or not self._local_fallback_model:
            yield LLMEvent(type="error", error=_PROVIDER_ERROR_MESSAGE)
            return

        logger.warning(
            "GroqClient: cloud provider unavailable -- failing over to local "
            "Ollama fallback (model=%s, base_url=%s)",
            self._local_fallback_model, self._local_fallback_base_url,
        )
        try:
            local_client = OllamaClient(model=self._local_fallback_model, base_url=self._local_fallback_base_url)
            async for event in local_client.stream_chat(messages, tools, system_prompt):
                if event.type == "error":
                    logger.warning("GroqClient: local Ollama fallback is also unavailable")
                    yield LLMEvent(type="error", error=_LOCAL_FALLBACK_UNAVAILABLE_MESSAGE)
                    return
                yield event
        except Exception:
            logger.exception("GroqClient: local Ollama fallback raised unexpectedly")
            yield LLMEvent(type="error", error=_LOCAL_FALLBACK_UNAVAILABLE_MESSAGE)


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
        # Live-verified on 2026-08-24: gemini-3.6-flash's default ("model
        # dependent") thinking budget added ~14.5s to a trivial single-turn
        # reply (thinking_budget=0 is rejected outright -- this model line
        # doesn't allow disabling thinking entirely, only reducing it via
        # thinking_level). "MINIMAL" cut that same call to ~2.7s with no
        # thoughts_token_count at all. This matters specifically because
        # chat's agent loop (agent.py) can make up to MAX_TOOL_ITERATIONS
        # sequential calls to this method for one user turn, all inside a
        # single Vercel serverless request bounded by a 60s hard ceiling
        # (see frontend's messages/route.ts) -- the default thinking budget
        # alone could exhaust that budget in 3-4 tool-calling round trips.
        config = genai_types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=gemini_tools,
            thinking_config=genai_types.ThinkingConfig(thinking_level="MINIMAL"),
            # Same cap and same reasoning as _MAX_COMPLETION_TOKENS above
            # (used for the OpenAI-shaped providers and Anthropic) -- bounds
            # worst-case completion cost/latency instead of relying on the
            # model's own default.
            max_output_tokens=_MAX_COMPLETION_TOKENS,
        )

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


class DualProviderClient:
    """Tier 1 (`primary`, e.g. Gemini) with Tier 2 (`secondary`, e.g. Groq)
    failover -- the same cloud-to-fallback pattern GroqClient.stream_chat
    already uses for its own cloud-to-local-Ollama step, just one level up
    and generic over which two clients are involved. If `primary` fails
    before yielding any real content, the whole request is retried against
    `secondary` (which may have its own further internal fallback chain --
    e.g. a GroqClient secondary already tries its configured fallback model,
    then Ollama, before giving up) instead of surfacing the raw error.

    Once real content has already reached the caller, failing over would
    risk a duplicated or inconsistent answer, so a failure past that point
    surfaces the plain error instead -- same reasoning as
    GroqClient.stream_chat's own cloud_failed/yielded_real_content guard.
    """

    def __init__(self, primary, secondary, primary_name: str, secondary_name: str):
        self._primary = primary
        self._secondary = secondary
        self._primary_name = primary_name
        self._secondary_name = secondary_name

    async def stream_chat(
        self, messages: list[Message], tools: list[ToolSpec], system_prompt: str
    ) -> AsyncIterator[LLMEvent]:
        primary_failed = False
        yielded_real_content = False
        async for event in self._primary.stream_chat(messages, tools, system_prompt):
            if event.type == "error":
                primary_failed = True
                break
            if event.type in ("token", "tool_call"):
                yielded_real_content = True
            yield event

        if not primary_failed:
            return

        if yielded_real_content:
            yield LLMEvent(type="error", error=_PROVIDER_ERROR_MESSAGE)
            return

        logger.warning(
            "DualProviderClient: %s unavailable -- failing over to %s",
            self._primary_name, self._secondary_name,
        )
        async for event in self._secondary.stream_chat(messages, tools, system_prompt):
            yield event


def _provider_api_key(current_settings, provider: str) -> str | None:
    if provider == "openai":
        return current_settings.openai_api_key
    if provider == "gemini":
        return current_settings.gemini_api_key
    if provider == "groq":
        return current_settings.groq_api_key
    return current_settings.anthropic_api_key


def _build_bare_client(current_settings, provider: str):
    """Constructs a single provider client with no dual-provider wrapping.

    Used both as get_llm_client()'s bottom-level provider resolution and as
    the primary/secondary building block inside _build_provider_client's
    Groq<->Gemini wrapping below -- wrapping *here* instead would let the
    "groq" and "gemini" branches call back into each other and recurse
    forever whenever both keys are configured.
    """
    if provider == "openai":
        return OpenAIClient(api_key=current_settings.openai_api_key, model=current_settings.openai_model)
    if provider == "gemini":
        return GeminiClient(api_key=current_settings.gemini_api_key, model=current_settings.gemini_model)
    if provider == "groq":
        return GroqClient(
            api_key=current_settings.groq_api_key,
            model=current_settings.groq_model,
            fallback_model=current_settings.groq_fallback_model,
            local_fallback_model=current_settings.ollama_model or None,
            local_fallback_base_url=current_settings.ollama_base_url,
        )
    return AnthropicClient(api_key=current_settings.anthropic_api_key, model=current_settings.anthropic_model)


def _build_provider_client(current_settings, provider: str):
    """Builds `provider` as Tier 1, wrapping it with the *other* of
    {groq, gemini} as a live Tier 2 failover (see DualProviderClient)
    whenever both a GROQ_API_KEY and a GEMINI_API_KEY are configured --
    works in either direction (Groq-primary-with-Gemini-fallback, or
    Gemini-primary-with-Groq-fallback) depending on which one LLM_PROVIDER
    names. With only one of the two keys set, this is unchanged from a bare
    single client. Groq keeps its own internal fallback-model and Ollama
    failover regardless of which role it's in here, so a chain with Groq
    involved is really failing over to Groq's *entire* existing chain, not
    just its primary model.
    """
    bare = _build_bare_client(current_settings, provider)
    if provider == "groq" and current_settings.gemini_api_key:
        secondary = _build_bare_client(current_settings, "gemini")
        return DualProviderClient(primary=bare, secondary=secondary, primary_name="Groq", secondary_name="Gemini")
    if provider == "gemini" and current_settings.groq_api_key:
        secondary = _build_bare_client(current_settings, "groq")
        return DualProviderClient(primary=bare, secondary=secondary, primary_name="Gemini", secondary_name="Groq")
    return bare


# get_llm_client() is called on every single chat turn/flagship-tool/worker
# invocation (see call sites in chat.py, flagship.py, files.py, tasks.py).
# Every branch below builds a real provider SDK client (AsyncAnthropic,
# AsyncOpenAI, GroqClient, genai.Client), each of which opens its own
# httpx.AsyncClient connection pool when none is passed in -- with no
# caching, every call leaked a fresh pool of sockets that async httpx
# clients cannot clean up via __del__ (their close is async). Memoized here
# the same way get_redis_client()/get_arq_pool() already are, keyed by the
# exact settings fields that affect which client gets built -- settings are
# fixed for the life of the process in production, so this is a one-time
# build in practice, while still rebuilding correctly whenever a test calls
# get_settings.cache_clear() with different env vars (see
# tests/unit/test_llm_providers.py, which relies on a fresh client per call).
_llm_client_cache_key: tuple | None = None
_llm_client_cache: object | None = None


def get_llm_client():
    global _llm_client_cache_key, _llm_client_cache
    current_settings = get_settings()
    cache_key = (
        current_settings.llm_provider,
        current_settings.anthropic_api_key,
        current_settings.anthropic_model,
        current_settings.openai_api_key,
        current_settings.openai_model,
        current_settings.gemini_api_key,
        current_settings.gemini_model,
        current_settings.groq_api_key,
        current_settings.groq_model,
        current_settings.groq_fallback_model,
        current_settings.ollama_model,
        current_settings.ollama_base_url,
    )
    if _llm_client_cache is not None and _llm_client_cache_key == cache_key:
        return _llm_client_cache

    client = _resolve_llm_client(current_settings)
    _llm_client_cache_key = cache_key
    _llm_client_cache = client
    return client


def _resolve_llm_client(current_settings):
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
