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


async def get_repo_or_404(db: AsyncSession, repo_id: UUID, user: User) -> Repo:
    # `user` is intentionally unused now -- kept in the signature so every
    # call site (files.py, conversations.py, jobs.py's inline check) needs
    # no argument-list change from the ownership-checked version this
    # replaces, only an import/name rename. Reads are public: any resource
    # that exists is readable by any valid token holder, per the approved
    # "fully public by URL" design (see the sub-project 3A spec).
    repo = await db.get(Repo, repo_id)
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found")
    return repo


async def get_conversation_or_404(db: AsyncSession, conversation_id: UUID, user: User) -> Conversation:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation
