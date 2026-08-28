import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, HttpUrl, field_validator

# `HttpUrl` alone only guarantees a well-formed http(s) URL -- it does NOT
# stop this value from being an SSRF vector once it reaches
# ingestion.clone_repo's `git.Repo.clone_from(url, ...)` call. Confirmed
# against real attack classes for this exact code path:
#   - SSRF: an attacker-supplied https:// URL pointing at an internal host
#     or cloud metadata endpoint (e.g. http://169.254.169.254/...) would be
#     cloned exactly like a real GitHub repo, from inside this service's
#     network.
#   - Git argument/transport injection: `git clone` treats some URL shapes
#     as CLI flags or alternate transports (e.g. a leading "-" is parsed as
#     an option; `ext::sh -c ...`-style transport helpers can execute
#     arbitrary commands) rather than a plain URL.
# Pinning both scheme AND host to exactly "github.com" over HTTPS closes
# all of the above at once: the resulting string always starts with
# "https://github.com/", which can never be interpreted as a flag or a
# non-http(s) transport, and can never resolve to an internal/metadata
# host (github.com always resolves to GitHub's own public infrastructure).
_ALLOWED_HOST = "github.com"
# owner/repo, optionally with a trailing .git and/or a trailing slash --
# GitHub owner/repo names are limited to alphanumerics, hyphens, underscores,
# and dots; rejecting anything else also rejects "..", encoded traversal
# sequences, and query/fragment smuggling attempts in the same step.
_REPO_PATH_RE = re.compile(r"^/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(?:\.git)?/?$")


class RepoAnalyzeRequest(BaseModel):
    repo_url: HttpUrl

    @field_validator("repo_url")
    @classmethod
    def _restrict_to_github_repo_url(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("repo_url must use https")
        if (value.host or "").lower() != _ALLOWED_HOST:
            raise ValueError("repo_url must be a github.com repository URL")
        # A non-default port on a URL that otherwise looks like
        # "https://github.com:XXXX/..." can't actually reach GitHub -- refuse
        # it rather than silently connecting somewhere else entirely.
        if value.port not in (None, 443):
            raise ValueError("repo_url must not specify a custom port")
        if value.username is not None or value.password is not None:
            raise ValueError("repo_url must not include embedded credentials")
        if not _REPO_PATH_RE.match(value.path or ""):
            raise ValueError("repo_url must look like https://github.com/<owner>/<repo>")
        return value


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


class TechStackExplainedEntry(BaseModel):
    name: str
    role: str


class LearningPathStep(BaseModel):
    file_or_topic: str
    why: str


class DomainBriefing(BaseModel):
    primary_field: str
    target_audience: str
    architecture_overview: str
    tech_stack_badges: list[str]
    file_type_distribution: list[FileTypeDistributionEntry]
    # Beginner-facing "onboarding guide" fields (see
    # app.core.domain_briefing.generate_domain_briefing). Defaulted rather
    # than required so a repo analyzed before this feature existed --
    # its stored domain_briefing JSONB simply lacks these keys -- still
    # validates instead of erroring the whole repo detail response.
    beginner_summary: str = ""
    tech_stack_explained: list[TechStackExplainedEntry] = []
    learning_path: list[LearningPathStep] = []
    key_takeaways: list[str] = []


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
