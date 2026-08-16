from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.models import Conversation, Repo, User
from app.db.session import get_db

_bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = payload["sub"]
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def get_owned_repo(db: AsyncSession, repo_id: UUID, user: User) -> Repo:
    repo = await db.get(Repo, repo_id)
    if repo is None or repo.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found")
    return repo


async def get_owned_conversation(db: AsyncSession, conversation_id: UUID, user: User) -> Conversation:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation
