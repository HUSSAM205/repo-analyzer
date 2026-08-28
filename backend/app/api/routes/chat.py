import asyncio
import contextlib
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.api.deps import get_conversation_or_404
from app.config import get_settings
from app.core.agent import run_agent
from app.core.conversation_summary import fold_into_summary
from app.core.deterministic_answer import build_deterministic_answer
from app.core.rate_limit import enforce_chat_rate_limit, enforce_ip_chat_rate_limit
from app.core.agent_tools import (
    LIST_DIRECTORY_TOOL_SPEC,
    READ_FILE_TOOL_SPEC,
    SEARCH_CODE_TOOL_SPEC,
    list_directory,
    read_file,
    search_code,
)
from app.core.llm import Message as AgentMessage
from app.core.llm_providers import get_llm_client
from app.core.token_budget import estimate_tokens
from app.db.models import Conversation, Message, MessageRole, Repo, User
from app.db.session import async_session_maker, get_db
from app.schemas.chat import SendMessageRequest

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/v1", tags=["chat"])

DEFAULT_CONVERSATION_TITLE = "New conversation"

# Recent raw messages kept verbatim in the agent's context on every turn,
# regardless of how long the conversation has grown -- this (not a large
# flat cutoff) is what keeps a single turn's cost, and therefore latency,
# constant even at 10,000+ turns instead of merely bounded-but-large.
# Anything older than this window is represented only by
# Conversation.summary (see app/core/conversation_summary.py and
# _maybe_extend_summary below), which itself only grows by a small, bounded
# amount per background update -- never by re-summarizing the whole
# conversation from scratch. 4 messages = the last 2 user/assistant turns.
# Tightened from 8 (4 turns) as part of a strict token-conservation pass --
# live-confirmed real, complete daily-quota exhaustion on both configured
# providers (Groq: shared 200k-token/day budget across its primary AND
# fallback model, both hit; Gemini: a hard 20-requests/day cap) largely
# from cumulative testing volume, not just real user traffic -- every token
# not spent on history/tool results/completion length is real headroom
# recovered for actual questions.
ROLLING_WINDOW_MESSAGES = 4

# A hard ceiling on the rolling window's total token cost, on top of the
# message-count cap above. ROLLING_WINDOW_MESSAGES bounds worst-case cost
# only if every message is short -- a conversation with a few long
# questions/answers (or one message containing a big pasted block of text)
# can still be large in tokens even at a small message count. Confirmed
# live: by a conversation's 3rd-5th turn, cumulative history + this turn's
# tool-call results (see CHAT_TOOL_RESULT_MAX_TOKENS below) was pushing
# single requests past Groq's per-minute token quota, surfacing as a 429
# the fallback chain in llm_providers.py couldn't fully absorb (both the
# primary and fallback model share the same account-wide quota). Trimming
# oldest-first here, same as the DB-message-count window this sits on top
# of, keeps the most recent (most relevant) exchange intact. Tightened from
# 1800 -- see ROLLING_WINDOW_MESSAGES's comment for why.
MAX_HISTORY_TOKENS = 800

# Per-tool-call budget used only for chat's agent loop -- deliberately much
# tighter than agent_tools.py's default MAX_CONTEXT_TOKENS (which is sized
# for a single one-shot flagship-tool prompt). A chat turn can accumulate up
# to MAX_TOOL_ITERATIONS separate tool results in the SAME growing message
# list (see agent.py's assistant_node, which resends the whole list on every
# iteration) -- at MAX_TOOL_ITERATIONS=3 (see agent.py), worst case is 3
# tool results in one turn. History: 900 -> 400 -> 600. The 400 step was
# live-verified too tight specifically for read_file on a real,
# moderately-long config file (pyproject.toml): its relevant section
# (pytest config) sat past the 400-token from-the-top cutoff, and the
# turn ran out of iterations re-exploring instead of ever seeing it.
# Raised to 600 *together with* read_file's new `query` param (see
# agent_tools.py's truncate_around_match) -- the fix for that failure mode
# is really "read the right section of the file," not "make the budget big
# enough that the top of any real file reaches far enough by luck." 600
# tokens/call is still well below the old 900, just no longer the single
# tightest constraint in the chain.
CHAT_TOOL_RESULT_MAX_TOKENS = 600

# Short conversational acknowledgments that never need repository lookups --
# offering tools for these just costs the model an extra decision (and,
# worse, an occasional wrongly-triggered tool call) for zero benefit. Matched
# by exact, normalized equality (not substring/regex) so a real question that
# happens to start with "thanks" or "ok" -- e.g. "ok but what does auth.py
# do" -- is never misclassified: normalizing it doesn't produce a set member.
_CHITCHAT_MESSAGES = frozenset({
    "ok", "okay", "kk", "k",
    "cool", "nice", "great", "awesome", "perfect",
    "thanks", "thank you", "thx", "ty", "much appreciated",
    "got it", "understood", "makes sense", "sounds good", "sounds great",
    "alright", "no problem", "np",
    "waiting", "still waiting", "one sec", "one moment", "hold on",
    "yes", "yeah", "yep", "yup", "no", "nope", "nah",
    "hi", "hello", "hey", "hiya",
    "bye", "goodbye", "see you", "later",
})
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def _is_chitchat(content: str) -> bool:
    normalized = _WHITESPACE_RE.sub(" ", _NON_ALNUM_RE.sub("", content.lower())).strip()
    return normalized in _CHITCHAT_MESSAGES


def _db_role_to_agent_role(role: MessageRole) -> str:
    return "user" if role == MessageRole.USER else "assistant"


def _trim_to_token_budget(messages: list[AgentMessage], max_tokens: int) -> list[AgentMessage]:
    """Drops oldest-first from `messages` until the total estimated token
    cost fits `max_tokens`, always keeping at least the newest message and
    re-applying the "must start with user" invariant afterward (same reason
    as the DB-message-count window this runs on top of -- see _load_history).
    """
    total = sum(estimate_tokens(m.content) for m in messages)
    start = 0
    while total > max_tokens and start < len(messages) - 1:
        total -= estimate_tokens(messages[start].content)
        start += 1
    trimmed = messages[start:]
    while trimmed and trimmed[0].role != "user":
        trimmed = trimmed[1:]
    return trimmed


async def _load_history(db: AsyncSession, conversation: Conversation) -> list[AgentMessage]:
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc())
        .limit(ROLLING_WINDOW_MESSAGES)
    )
    recent_messages = list(reversed(result.scalars().all()))
    # A failed turn commits only the user message (the error path never
    # persists an assistant reply), which can permanently shift the
    # user/assistant alternation parity for a conversation. If that has
    # happened, a bounded window computed purely by count can start with an
    # assistant message -- and Anthropic's Messages API requires the first
    # message in the array to have role "user", rejecting the request
    # otherwise. Drop any leading non-user messages so the window always
    # starts on a user message.
    while recent_messages and recent_messages[0].role != MessageRole.USER:
        recent_messages.pop(0)
    recent = [AgentMessage(role=_db_role_to_agent_role(m.role), content=m.content) for m in recent_messages]
    recent = _trim_to_token_budget(recent, MAX_HISTORY_TOKENS)

    if not conversation.summary:
        return recent

    # Injected as an ordinary synthetic user/assistant exchange at the front
    # of the list, rather than folded into the system prompt -- keeps this
    # provider-agnostic (no per-provider special-casing needed) and
    # preserves user/assistant alternation for providers that care, since
    # the recent window above is already guaranteed to start on "user".
    summary_context = [
        AgentMessage(role="user", content="(For context, please recall the earlier part of this conversation.)"),
        AgentMessage(role="assistant", content=f"Summary of earlier conversation:\n{conversation.summary}"),
    ]
    return [*summary_context, *recent]


async def _maybe_extend_summary(conversation_id: UUID) -> None:
    """Background step (see send_message's StreamingResponse `background=`):
    folds any messages that have newly aged out of the rolling window into
    Conversation.summary.

    Runs only after the SSE stream has already been fully sent to the
    client, so it never adds to user-visible chat latency. Uses its own DB
    session and a fresh LLM client since the request-scoped ones are no
    longer valid/in-scope by the time this runs. Bounded cost regardless of
    total conversation length: only the count is fetched for the whole
    conversation (a single indexed COUNT), and only the newly-aged-out
    slice (normally just the last exchange, 2 messages) is ever fetched or
    summarized -- never the full history.
    """
    try:
        async with async_session_maker() as db:
            conversation = await db.get(Conversation, conversation_id)
            if conversation is None:
                return

            total = await db.scalar(
                select(func.count()).select_from(Message).where(Message.conversation_id == conversation_id)
            )
            fold_up_to = max((total or 0) - ROLLING_WINDOW_MESSAGES, 0)
            already_covered = conversation.summary_covers_through_message_count
            if fold_up_to <= already_covered:
                return

            result = await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at)
                .offset(already_covered)
                .limit(fold_up_to - already_covered)
            )
            new_slice = [
                AgentMessage(role=_db_role_to_agent_role(m.role), content=m.content) for m in result.scalars().all()
            ]

            llm_client = get_llm_client()
            updated_summary = await fold_into_summary(llm_client, conversation.summary, new_slice)

            conversation.summary = updated_summary
            conversation.summary_covers_through_message_count = fold_up_to
            await db.commit()
    except Exception:
        logger.exception("Background conversation-summary update failed for conversation_id=%s", conversation_id)


_TITLE_MAX_LENGTH = 60


def _derive_title(content: str) -> str:
    single_line = " ".join(content.split())
    if len(single_line) <= _TITLE_MAX_LENGTH:
        return single_line
    truncated = single_line[:_TITLE_MAX_LENGTH].rsplit(" ", 1)[0] or single_line[:_TITLE_MAX_LENGTH]
    return f"{truncated}..."


def _sse_event(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


# A ":"-prefixed line is an SSE *comment* per the spec -- no "event:"/
# "data:" fields, so EventSource and this frontend's own hand-rolled parser
# (lib/sse.ts's parseSSEChunk, which requires both an event and data line
# per frame) silently ignore it. Sent periodically while waiting on a slow
# tool call or LLM round-trip so an idle-looking connection still has bytes
# flowing across it -- without this, a long enough gap between real events
# risks a proxy/load-balancer/browser treating the stream as dead and
# dropping it before the real answer ever arrives.
_SSE_HEARTBEAT = ": keep-alive\n\n"

# Comfortably under any intermediary's typical idle-connection timeout
# (commonly 30-60s) while still rare enough not to meaningfully add to
# stream volume -- a normal turn emits real events far more often than
# this regardless (token-by-token streaming), so heartbeats in practice
# only ever fire during a genuinely slow tool call or provider round-trip.
_HEARTBEAT_INTERVAL_SECONDS = 15.0

# Sentinel marking "the agent's event stream ended normally" on the queue
# below -- distinguished from a real LLMEvent (never this exact object) and
# from an Exception instance (the agent's stream ended abnormally).
_AGENT_STREAM_DONE = object()


# Keeps a strong reference to a producer task for as long as it's still
# running, in the (rare) case the consumer loop below exits early -- e.g.
# a DB error while persisting the assistant message -- while the producer
# is still draining run_agent()'s stream. Without this, losing the local
# `producer_task` reference when event_stream() itself returns risks
# asyncio garbage-collecting a still-pending Task mid-execution (a
# documented asyncio gotcha, not hypothetical -- "Task was destroyed but
# it is pending!"). Each task discards itself once done.
_background_agent_drains: set[asyncio.Task] = set()


async def _drain_agent_stream(agent_iter: AsyncIterator, queue: "asyncio.Queue[object]") -> None:
    """Consumes `agent_iter` (run_agent()'s event stream) into `queue` on
    its own task, independent of however often (or rarely) the caller
    actually checks the queue.

    This indirection -- rather than the caller iterating run_agent()
    directly with an asyncio.wait_for(..., timeout=...) around each
    __anext__() call -- exists specifically so a heartbeat timeout can
    never cancel an in-flight step of the underlying LangGraph astream().
    Cancelling a paused async generator's __anext__() injects a
    cancellation into its suspended frame, which (see event_stream's own
    comment on LangGraph 0.2.45's PregelRunner) is exactly the kind of
    forced-early-closure this codebase already had to work around once
    for a different reason (a leaked background Task at teardown). Here,
    only queue.get() is ever subject to a timeout -- cancelling that is
    always safe, and this producer task keeps running unaffected either
    way, so the agent's own stream is always drained to completion on its
    own terms.
    """
    try:
        async for event in agent_iter:
            await queue.put(event)
        await queue.put(_AGENT_STREAM_DONE)
    except Exception as exc:
        await queue.put(exc)


_GENERIC_DEGRADED_REPLY = (
    "I'm temporarily unable to reach the AI provider right now (most likely a brief "
    "rate limit) -- your question wasn't lost, please try sending it again in a moment."
)


async def _graceful_degraded_reply(repo_id: UUID, question: str) -> str:
    """Builds a still-useful reply for when the LLM provider is genuinely
    unreachable (both the primary and fallback model exhausted -- see
    GroqClient.stream_chat), instead of a bare "provider unavailable" error.

    Three-tier degrade, cheapest/most-specific first:
    1. A keyword-grounded match against this repo's indexed files (see
       deterministic_answer.py) -- no LLM call, answers the ACTUAL question
       when it can.
    2. `repo.domain_briefing` (already generated and cached at analysis
       time, so this needs no LLM call either) -- generic but still
       concrete about this specific repo.
    3. A fully generic "try again" message, if even the repo lookup fails.
    Never raises -- this runs from inside an already-failing path, so a
    second failure here must degrade further, not propagate.
    """
    try:
        async with async_session_maker() as db:
            deterministic = await build_deterministic_answer(db, repo_id, question)
            if deterministic is not None:
                return deterministic

            repo = await db.get(Repo, repo_id)
            briefing = repo.domain_briefing if repo else None
        if not briefing:
            return _GENERIC_DEGRADED_REPLY

        parts = [
            "I'm temporarily rate-limited and can't research your specific question "
            "right now, but here's what I already know about this repository:",
        ]
        audience = briefing.get("target_audience")
        if audience:
            parts.append(f"It's built for {audience.rstrip('.')}.")
        overview = briefing.get("architecture_overview")
        if overview:
            parts.append(overview)
        parts.append("Please try again in a moment for a detailed, code-grounded answer.")
        return " ".join(parts)
    except Exception:
        logger.exception("Failed to build graceful degraded reply for repo_id=%s", repo_id)
        return _GENERIC_DEGRADED_REPLY


@router.post("/conversations/{conversation_id}/messages", dependencies=[Depends(enforce_ip_chat_rate_limit)])
async def send_message(
    conversation_id: UUID,
    payload: SendMessageRequest,
    current_user: Annotated[User, Depends(enforce_chat_rate_limit)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    conversation = await get_conversation_or_404(db, conversation_id, current_user)
    repo_id = conversation.repo_id
    conversation_id_value = conversation.id

    history = await _load_history(db, conversation)

    # A conversation picker full of indistinguishable "New conversation"
    # entries (see ConversationCreate's default title) isn't very useful for
    # actually switching between chat histories -- give it a real title
    # derived from the first message once there is one to derive it from.
    # Only ever overwrites the exact default title, never a title the user
    # (or a future rename feature) has already set.
    if not history and conversation.title == DEFAULT_CONVERSATION_TITLE:
        conversation.title = _derive_title(payload.content)

    user_message = Message(conversation_id=conversation_id_value, role=MessageRole.USER, content=payload.content)
    db.add(user_message)
    await db.commit()

    async def _persist_and_emit_degraded_reply(content: str) -> AsyncIterator[str]:
        # Used only by the graceful-degradation paths below (provider
        # exhausted, or not configured at all) -- unlike the normal
        # message_done path, no "token" events have streamed yet here, so
        # this synthesizes one so the frontend renders the reply as a normal
        # chat bubble instead of an empty one. Still falls back to a raw SSE
        # "error" event if even this fails (e.g. the DB itself is down) --
        # a narrow last resort, not the common path this turn's fix targets.
        yield _sse_event("token", {"text": content})
        try:
            async with async_session_maker() as save_db:
                assistant_message = Message(
                    conversation_id=conversation_id_value, role=MessageRole.ASSISTANT, content=content
                )
                save_db.add(assistant_message)
                await save_db.commit()
                await save_db.refresh(assistant_message)
            yield _sse_event("done", {"message_id": str(assistant_message.id)})
        except Exception:
            logger.exception(
                "Failed to persist degraded assistant reply for conversation_id=%s", conversation_id_value
            )
            yield _sse_event("error", {"message": "An unexpected error occurred while generating the response."})

    async def event_stream() -> AsyncIterator[str]:
        try:
            llm_client = get_llm_client()
        except Exception:
            logger.exception("get_llm_client() failed for conversation_id=%s", conversation_id_value)
            async for chunk in _persist_and_emit_degraded_reply(await _graceful_degraded_reply(repo_id, payload.content)):
                yield chunk
            return

        conversation_messages = [*history, AgentMessage(role="user", content=payload.content)]

        async def search_fn(args: dict) -> str:
            async with async_session_maker() as search_db:
                return await search_code(
                    search_db, repo_id, args.get("query", ""), max_tokens=CHAT_TOOL_RESULT_MAX_TOKENS
                )

        async def list_directory_fn(args: dict) -> str:
            async with async_session_maker() as search_db:
                return await list_directory(search_db, repo_id, args.get("path", ""))

        async def read_file_fn(args: dict) -> str:
            async with async_session_maker() as search_db:
                return await read_file(
                    search_db, repo_id, args.get("path", ""), query=args.get("query"),
                    max_tokens=CHAT_TOOL_RESULT_MAX_TOKENS,
                )

        # A short conversational reply ("ok", "thanks", "waiting") never
        # needs a repository lookup -- offering tools at all just risks an
        # unnecessary (and purely latency-adding) tool call for a message
        # that has nothing to look up. No tools bound means the model
        # structurally cannot call one, rather than merely being asked not
        # to via the system prompt.
        # search_code is excluded entirely (not just left to return empty
        # results) when embedding is disabled -- see Settings.
        # enable_embedding. Nothing populates the vector index in that
        # case, so offering the tool at all would just waste a turn on a
        # call that can never find anything.
        if _is_chitchat(payload.content):
            tool_specs = []
            tool_functions = {}
        elif settings.enable_embedding:
            tool_specs = [SEARCH_CODE_TOOL_SPEC, LIST_DIRECTORY_TOOL_SPEC, READ_FILE_TOOL_SPEC]
            tool_functions = {
                "search_code": search_fn,
                "list_directory": list_directory_fn,
                "read_file": read_file_fn,
            }
        else:
            tool_specs = [LIST_DIRECTORY_TOOL_SPEC, READ_FILE_TOOL_SPEC]
            tool_functions = {
                "list_directory": list_directory_fn,
                "read_file": read_file_fn,
            }

        assistant_text = ""
        # Once message_done has been handled, ignore any further events
        # instead of returning early. This makes "persist and forward the
        # assistant message exactly once" structural -- it no longer relies
        # on run_agent() never emitting anything after message_done -- while
        # still letting run_agent()'s underlying LangGraph astream() drain to
        # its own natural StopAsyncIteration. Returning early instead (i.e.
        # abandoning that async generator before it finishes on its own) was
        # tried and reintroduces a real side effect: LangGraph 0.2.45's
        # PregelRunner spawns a background asyncio Task for stream_mode
        # "custom" delivery that is only cleaned up as part of the
        # generator's normal exit path, not on forced closure/GeneratorExit
        # -- forcing early closure leaks that task until garbage collection,
        # which then throws "Task was destroyed but it is pending!" (and, if
        # GC happens after the loop has closed, "Event loop is closed") at
        # process/loop teardown. Draining fully avoids that entirely.
        done_emitted = False
        agent_queue: asyncio.Queue[object] = asyncio.Queue()
        producer_task = asyncio.create_task(
            _drain_agent_stream(run_agent(llm_client, tool_specs, tool_functions, conversation_messages), agent_queue)
        )
        _background_agent_drains.add(producer_task)
        producer_task.add_done_callback(_background_agent_drains.discard)
        try:
            while True:
                # A heartbeat-interval timeout on the QUEUE (not on the
                # agent's own stream) is always safe to let expire and
                # retry -- see _drain_agent_stream's docstring for why this
                # indirection exists at all.
                try:
                    item = await asyncio.wait_for(agent_queue.get(), timeout=_HEARTBEAT_INTERVAL_SECONDS)
                except asyncio.TimeoutError:
                    yield _SSE_HEARTBEAT
                    continue
                if item is _AGENT_STREAM_DONE:
                    break
                if isinstance(item, Exception):
                    raise item
                event = item
                if done_emitted:
                    continue
                if event.type == "token":
                    assistant_text += event.token or ""
                    yield _sse_event("token", {"text": event.token})
                elif event.type == "tool_call":
                    # Generic across all three tools: forwards whatever
                    # arguments this call actually has (query for
                    # search_code, path for list_directory/read_file)
                    # alongside which tool it is. The frontend currently
                    # only uses this event's presence (to show a generic
                    # "working..." status), not its field contents, so this
                    # is a compatible superset of the old {"query": ...}
                    # shape rather than a breaking change.
                    tc = event.tool_calls[0] if event.tool_calls else None
                    tool_call_data = {"tool": tc.name, **tc.arguments} if tc else {"tool": None}
                    yield _sse_event("tool_call", tool_call_data)
                elif event.type == "tool_result":
                    summary = (event.tool_result_text or "")[:200]
                    yield _sse_event("tool_result", {"summary": summary})
                elif event.type == "message_done":
                    # `assistant_text` accumulates every "token" event across
                    # the WHOLE interaction (every turn, including preamble
                    # text streamed before a tool call on earlier turns) --
                    # not just the final turn. Using event.message.content
                    # here would silently drop that preamble from what gets
                    # persisted, even though the client already saw it stream
                    # by, because it only reflects the LAST turn's content.
                    # A turn's final text is itself streamed as "token"
                    # events before message_done fires (see agent.py's
                    # assistant_node), so assistant_text is already complete
                    # -- event.message is only a signal that the turn is
                    # done, not an independent source of text. strip() drops
                    # only the harmless trailing space FakeLLMClient's
                    # word-by-word tokenizer appends after the last token.
                    #
                    # One case still needs event.message.content as a
                    # fallback: the agent's max-tool-iterations give-up
                    # message (see app/core/agent.py) is emitted directly via
                    # a message_done event with no preceding token events at
                    # all, so assistant_text is empty in that case even
                    # though there is real explanatory text to persist.
                    final_text = assistant_text.strip() or (event.message.content if event.message else "")
                    # Confirmed live: a model can end a turn with tool_calls
                    # empty AND real text empty -- e.g. gpt-oss-20b's entire
                    # response was reasoning wrapped in <think>...</think>
                    # with nothing after it, which _ThinkTagFilter (see
                    # llm_providers.py) correctly strips as not being a real
                    # answer, leaving nothing behind. Persisting "" and
                    # reporting "done" anyway left a genuinely blank
                    # assistant turn with no explanation and no way to
                    # retry (the frontend's Retry button only appears on an
                    # "error" event). A short, honest fallback message is
                    # better than a silent empty bubble.
                    if not final_text:
                        final_text = (
                            "I wasn't able to come up with a response for that. "
                            "Could you try rephrasing your question?"
                        )
                    # Both fallback cases above (the empty-response message
                    # right above, and the agent's max-tool-iterations give-up
                    # message -- see agent.py's assistant_node) reach here with
                    # `assistant_text` still empty: no "token" events were ever
                    # streamed for this turn, only a message_done carrying the
                    # text directly. Live-verified: the frontend's chat bubble
                    # is built purely from accumulated "token" events during
                    # streaming (see chat-message.tsx), so without this, the
                    # live client saw an empty bubble and only "done" -- the
                    # text was silently persisted to the DB and only became
                    # visible on the next full conversation reload. Stream it
                    # now so a live viewer sees the same explanatory text
                    # that's about to be saved.
                    if not assistant_text.strip():
                        yield _sse_event("token", {"text": final_text})
                    async with async_session_maker() as save_db:
                        assistant_message = Message(
                            conversation_id=conversation_id_value, role=MessageRole.ASSISTANT, content=final_text
                        )
                        save_db.add(assistant_message)
                        await save_db.commit()
                        await save_db.refresh(assistant_message)
                    yield _sse_event("done", {"message_id": str(assistant_message.id)})
                    done_emitted = True
                elif event.type == "error":
                    # By this point GroqClient has already exhausted its own
                    # internal fallback (primary model -> configured fallback
                    # model -> local Ollama if configured) -- see
                    # llm_providers.py. Rather than surface that as a raw SSE
                    # "error" event (rendered as a hard red failure bubble by
                    # the frontend), degrade to a still-useful reply so a
                    # provider-side rate limit never looks like the product
                    # itself crashed.
                    logger.warning(
                        "LLM provider exhausted for conversation_id=%s -- degrading gracefully: %s",
                        conversation_id_value, event.error,
                    )
                    async for chunk in _persist_and_emit_degraded_reply(await _graceful_degraded_reply(repo_id, payload.content)):
                        yield chunk
                    done_emitted = True
        except Exception:
            logger.exception("chat stream failed for conversation_id=%s", conversation_id_value)
            async for chunk in _persist_and_emit_degraded_reply(await _graceful_degraded_reply(repo_id, payload.content)):
                yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            # Belt-and-suspenders against any intermediary (Render's edge
            # proxy, a CDN, an nginx hop) buffering the response instead of
            # forwarding each chunk as it's written -- buffering would turn
            # an otherwise-instant token stream into one big delayed burst
            # right before the connection closes, defeating the point of
            # streaming. Cache-Control/Connection reinforce the same intent
            # for any HTTP/1.1-era cache in the path; X-Accel-Buffering is
            # the nginx-specific opt-out and is harmless where nginx isn't
            # in the path.
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
        # Runs once the streamed body has been fully sent to the client --
        # i.e. strictly after the user has already seen their answer -- so
        # extending the conversation's rolling summary (see
        # _maybe_extend_summary) never adds to this turn's visible latency.
        background=BackgroundTask(_maybe_extend_summary, conversation_id_value),
    )
