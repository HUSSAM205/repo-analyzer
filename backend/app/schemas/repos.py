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


class RepoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    name: str
    status: str
    created_at: datetime
    # Populated only by GET /repos/{repo_id} (the single-repo detail
    # endpoint), not by GET /repos (list), to avoid an N+1 query on the list
    # view. Lets the frontend show a repo's failure reason without relying
    # on a `?job=<id>` query param that's only set once at submission time
    # and lost on reload or a shared link.
    latest_job: JobResponse | None = None
