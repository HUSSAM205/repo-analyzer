# Repo Analyzer — Sub-Project 1: Foundation + Analysis Core

Status: Approved
Date: 2026-08-16

## Purpose

Build the ingestion → parsing → embedding → search engine for the
Autonomous AI GitHub Repository Deep Analyzer platform. This is the
first of several sub-projects (see "Future sub-projects" below); it
proves the core value proposition — can we clone a real repo, parse
it with AST awareness, embed it locally, and search it semantically —
before any multi-agent orchestration or frontend is built on top.

This is a real product the user intends to run, not a demo. Backend
only: verified via API calls and automated tests, no UI in this phase.

## Non-goals (this sub-project)

- No frontend (Next.js UI is sub-project 4)
- No LangGraph multi-agent workflow (sub-project 3)
- No org/RBAC, multi-tenant workspaces beyond one-workspace-per-user
- No load testing to 1000+ concurrent sessions — the async job-queue
  architecture is what *enables* that scale, but proving it under
  load is a separate, later exercise
- No Kubernetes/production deployment — docker-compose only

## Architecture

Async job-queue model (Redis + ARQ), not synchronous in-request
processing. A repo clone + parse + embed can take minutes; the API
must return immediately with a job id and let a background worker do
the work, with progress polling. This is required for the "handles
real repos without blocking" property and matches the intended
Redis-backed background job queuing.

### Project layout

```
repo-analyzer/
  backend/
    app/
      main.py, config.py            # FastAPI app, Pydantic v2 settings
      api/routes/                   # repos, jobs, search, auth
      db/                           # SQLAlchemy 2.0 async models, Alembic migrations
      workers/                      # ARQ worker + task pipeline
      core/                         # ast_parser, chunker, embeddings, search, security
      schemas/                      # Pydantic v2 request/response models
    tests/{unit,integration}/
    Dockerfile, requirements.txt
  docker-compose.yml                # postgres+pgvector, redis, api, worker
  .env.example, README.md
```

## Data flow

1. `POST /api/v1/repos/analyze {repo_url}` — validates the URL,
   creates `Repo` and `Job` rows (status=pending), enqueues an ARQ
   job, returns `{job_id}` immediately.
2. ARQ worker picks up the job:
   - Shallow git clone to a temp dir (size/file-count caps enforced,
     configurable via env).
   - Walk files; skip binaries/vendored dirs by convention
     (node_modules, .git, dist, build, etc.).
   - Tree-sitter AST parse per file. Supported languages at launch:
     Python, JavaScript/TypeScript, Go, Java — implemented as a
     parser registry so more languages can be added without touching
     the pipeline. Unsupported languages fall back to sliding-window
     text chunking so ingestion never hard-fails on an unfamiliar
     language.
   - Chunk at function/class granularity from the AST (fallback:
     fixed-size overlapping windows for non-AST text).
   - Batch-embed each chunk with `microsoft/codebert-base` (HF
     Transformers, CPU/torch — no GPU required).
   - Store chunk + embedding (pgvector column) + metadata (file path,
     symbol name, node type, start/end line, a tsvector column for
     lexical search).
   - Update job progress incrementally (files processed / total).
3. `GET /api/v1/jobs/{job_id}` — poll status, progress, error message,
   skipped-file count.
4. `POST /api/v1/search {repo_id, query, mode?}` — embeds the query,
   runs pgvector cosine similarity and Postgres full-text search in
   parallel, merges via reciprocal rank fusion, returns ranked chunks
   with file/line references.

## Database schema (Postgres + pgvector)

- `users(id, email, hashed_password, created_at)`
- `api_keys(id, user_id, hashed_key, name, created_at, last_used_at)`
- `repos(id, user_id, url, name, default_branch, status, created_at)`
- `jobs(id, repo_id, status, progress, error_message, skipped_files, started_at, finished_at)`
- `code_chunks(id, repo_id, file_path, symbol_name, node_type, start_line, end_line, content, embedding vector(768), content_tsv tsvector)`
  - `ivfflat` (or `hnsw`, whichever the installed pgvector version
    supports) index on `embedding`; GIN index on `content_tsv`

## Auth

JWT (RS256) for user sessions; hashed API keys for programmatic
access. Single-tenant-per-user workspace model — real auth, not a
full org/RBAC system (that's a later hardening phase if ever needed).

## Error handling

- Per-file parse failures are logged and skipped; the job still
  succeeds overall, with a `skipped_files` count surfaced on the job.
- Clone failures (invalid URL, private repo without access, repo over
  the configured size cap) fail the job with a clear `error_message`
  and the temp clone directory is cleaned up.
- Worker fails fast at startup if the embedding model can't load
  (health check), rather than failing per-job.
- `POST /repos/analyze` is rate-limited per user via a Redis token
  bucket to prevent one user from queuing unbounded jobs.

## Testing

- Unit tests: AST parser against fixture snippets per supported
  language, chunk boundary correctness, embedding output shape,
  hybrid search ranking/fusion logic, JWT auth flows.
- Integration tests: full pipeline run against a small fixture repo
  checked into the test suite (not live GitHub network calls),
  against a real test Postgres+pgvector and Redis instance — assert
  chunks land in the DB with correct metadata and that search returns
  the expected chunk for a known query.
- No Playwright in this sub-project (no frontend yet).

## Future sub-projects (not in scope here)

2. Multi-agent intelligence — LangGraph agents (pluggable
   Anthropic/OpenAI) using this search core to answer questions, map
   call graphs, generate architecture summaries, "chat with repo."
3. Frontend UX — interactive file tree, dependency graph, code diff
   viewer, chat UI, Mermaid architecture diagrams.
4. Enterprise hardening — rate limiting beyond the basic token
   bucket, LLM guardrails, workspaces/telemetry, Celery/ARQ at scale.
5. DevOps & testing — multi-stage Dockerfiles, full docker-compose
   orchestration, Playwright e2e, CI integration tests.
