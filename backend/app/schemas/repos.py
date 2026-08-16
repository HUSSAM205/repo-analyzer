import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, HttpUrl


class RepoAnalyzeRequest(BaseModel):
    repo_url: HttpUrl


class RepoAnalyzeResponse(BaseModel):
    repo_id: uuid.UUID
    job_id: uuid.UUID


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repo_id: uuid.UUID
    status: str
    progress: int
    error_message: str | None
    skipped_files: int
    started_at: datetime | None
    finished_at: datetime | None
