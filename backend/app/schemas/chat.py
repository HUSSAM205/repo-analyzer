import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", min_length=1, max_length=255)


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repo_id: uuid.UUID
    title: str
    created_at: datetime


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    created_at: datetime


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
