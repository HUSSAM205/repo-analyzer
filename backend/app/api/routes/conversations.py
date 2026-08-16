from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_owned_conversation, get_owned_repo
from app.db.models import Conversation, Message, User
from app.db.session import get_db
from app.schemas.chat import ConversationCreate, ConversationResponse, MessageResponse

router = APIRouter(prefix="/api/v1", tags=["conversations"])


@router.post("/repos/{repo_id}/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    repo_id: UUID,
    payload: ConversationCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Conversation:
    await get_owned_repo(db, repo_id, current_user)
    conversation = Conversation(repo_id=repo_id, user_id=current_user.id, title=payload.title)
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.get("/repos/{repo_id}/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    repo_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Conversation]:
    await get_owned_repo(db, repo_id, current_user)
    result = await db.execute(
        select(Conversation)
        .where(Conversation.repo_id == repo_id, Conversation.user_id == current_user.id)
        .order_by(Conversation.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
async def get_messages(
    conversation_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Message]:
    conversation = await get_owned_conversation(db, conversation_id, current_user)
    result = await db.execute(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)
    )
    return list(result.scalars().all())
