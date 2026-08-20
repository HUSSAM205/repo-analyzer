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
    # One of "cloning", "parsing", "embedding", "completed" while/after the
    # pipeline runs; None for a job that hasn't started yet.
    stage: str | None = None
    error_message: str | None
    skipped_files: int
    started_at: datetime | None
    finished_at: datetime | None


class FileTypeDistributionEntry(BaseModel):
    label: str
    count: int


class DomainBriefing(BaseModel):
    primary_field: str
    target_audience: str
    architecture_overview: str
    tech_stack_badges: list[str]
    file_type_distribution: list[FileTypeDistributionEntry]


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
    # The "Domain & Purpose Classification" briefing produced once analysis
    # completes -- see app.core.domain_briefing.generate_domain_briefing.
    # None until analysis has finished (or if the repo predates this field).
    domain_briefing: DomainBriefing | None = None
