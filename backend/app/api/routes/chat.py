import json
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

router = APIRouter(prefix="/api/v1", tags=["chat"])


def _db_role_to_agent_role(role: MessageRole) -> str:
    return "user" if role == MessageRole.USER else "assistant"


async def _load_history(db: AsyncSession, conversation_id: UUID) -> list[AgentMessage]:
    result = await db.execute(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
    )
    return [AgentMessage(role=_db_role_to_agent_role(m.role), content=m.content) for m in result.scalars().all()]


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
        except RuntimeError as exc:
            yield _sse_event("error", {"message": str(exc)})
            return

        conversation_messages = [*history, AgentMessage(role="user", content=payload.content)]

        async def search_fn(query: str) -> str:
            async with async_session_maker() as search_db:
                return await search_code(search_db, repo_id, query)

        assistant_text = ""
        try:
            async for event in run_agent(llm_client, search_fn, conversation_messages):
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
                    final_text = event.message.content if event.message else assistant_text
                    async with async_session_maker() as save_db:
                        assistant_message = Message(
                            conversation_id=conversation_id_value, role=MessageRole.ASSISTANT, content=final_text
                        )
                        save_db.add(assistant_message)
                        await save_db.commit()
                        await save_db.refresh(assistant_message)
                    yield _sse_event("done", {"message_id": str(assistant_message.id)})
                elif event.type == "error":
                    yield _sse_event("error", {"message": event.error or "The assistant hit an unexpected error."})
        except Exception as exc:
            yield _sse_event("error", {"message": f"Unexpected error: {exc}"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
