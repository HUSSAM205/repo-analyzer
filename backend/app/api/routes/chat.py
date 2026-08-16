import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_owned_conversation
from app.core.agent import run_agent
from app.core.agent_tools import search_code
from app.core.llm import Message as AgentMessage
from app.core.llm_providers import get_llm_client
from app.db.models import Message, MessageRole, User
from app.db.session import async_session_maker, get_db
from app.schemas.chat import SendMessageRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["chat"])

# Cap how much prior conversation gets fed back into the agent on each turn.
# Without a bound, a long-running conversation eventually exceeds the model's
# context window on every subsequent send -- and since the user's message is
# committed before the stream starts, each failed retry adds another message
# and makes the conversation permanently unusable. 40 messages is roughly 20
# user/assistant exchanges, a reasonable working-memory window.
MAX_HISTORY_MESSAGES = 40


def _db_role_to_agent_role(role: MessageRole) -> str:
    return "user" if role == MessageRole.USER else "assistant"


async def _load_history(db: AsyncSession, conversation_id: UUID) -> list[AgentMessage]:
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(MAX_HISTORY_MESSAGES)
    )
    recent_messages = list(reversed(result.scalars().all()))
    return [AgentMessage(role=_db_role_to_agent_role(m.role), content=m.content) for m in recent_messages]


def _sse_event(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: UUID,
    payload: SendMessageRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    conversation = await get_owned_conversation(db, conversation_id, current_user)
    repo_id = conversation.repo_id
    conversation_id_value = conversation.id

    history = await _load_history(db, conversation_id_value)

    user_message = Message(conversation_id=conversation_id_value, role=MessageRole.USER, content=payload.content)
    db.add(user_message)
    await db.commit()

    async def event_stream() -> AsyncIterator[str]:
        try:
            llm_client = get_llm_client()
        except Exception:
            logger.exception("get_llm_client() failed for conversation_id=%s", conversation_id_value)
            yield _sse_event(
                "error", {"message": "The chat assistant is not configured. Please contact the administrator."}
            )
            return

        conversation_messages = [*history, AgentMessage(role="user", content=payload.content)]

        async def search_fn(query: str) -> str:
            async with async_session_maker() as search_db:
                return await search_code(search_db, repo_id, query)

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
        try:
            async for event in run_agent(llm_client, search_fn, conversation_messages):
                if done_emitted:
                    continue
                if event.type == "token":
                    assistant_text += event.token or ""
                    yield _sse_event("token", {"text": event.token})
                elif event.type == "tool_call":
                    query = event.tool_calls[0].arguments.get("query", "") if event.tool_calls else ""
                    yield _sse_event("tool_call", {"query": query})
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
                    final_text = assistant_text.strip()
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
                    yield _sse_event("error", {"message": event.error or "The assistant hit an unexpected error."})
        except Exception:
            logger.exception("chat stream failed for conversation_id=%s", conversation_id_value)
            yield _sse_event(
                "error", {"message": "An unexpected error occurred while generating the response."}
            )

    return StreamingResponse(event_stream(), media_type="text/event-stream")
