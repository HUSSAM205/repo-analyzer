# RepoLens AI

[![Live Demo](https://img.shields.io/badge/demo-live-brightgreen)](https://repolens-ai-app.vercel.app)
[![Frontend](https://img.shields.io/badge/frontend-Next.js%2014-black)](frontend)
[![Backend](https://img.shields.io/badge/backend-FastAPI-009688)](backend)

**[repolens-ai-app.vercel.app](https://repolens-ai-app.vercel.app)** — paste any public
GitHub URL and get an instant AST-level architectural briefing, syntax-highlighted
file browsing, and an AI chat that answers questions by actually reading the
repo's code.

Clone a repo, parse it with Tree-sitter, chunk it at function/class
granularity, embed chunks locally with CodeBERT, and search it via hybrid
(vector + keyword) search — with a full Next.js frontend (file tree, code
viewer, streaming chat, and flagship analysis tools) on top. This section
covers the backend analysis core specifically; see [Frontend](#frontend-sub-project-2b)
below for the UI.

## Setup

1. `cd backend && python -m venv .venv && source .venv/Scripts/activate`
2. `pip install -r requirements.txt`
3. `python scripts/generate_keys.py` — generates a local JWT RS256 keypair
   (gitignored; regenerate per environment)
4. `cp .env.example .env`
5. From the repo root: `docker compose up -d postgres redis`
6. `cd backend && alembic upgrade head`
7. Run the API locally: `uvicorn app.main:app --reload`
   Run the worker locally: `arq app.workers.settings.WorkerSettings`

   Or run the full containerized stack instead of steps 6-7:
   `docker compose up -d --build` then `docker compose exec api alembic upgrade head`

## Tests

- Fast unit tests (no external services): `pytest -m "not integration and not slow"`
- Integration tests (needs `docker compose up -d postgres redis`): `pytest -m integration`
- Slow tests (downloads/runs the real CodeBERT model, ~500MB first run): `pytest -m slow`
- Everything: `pytest`

## Example walkthrough

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" -d '{"email":"you@example.com","password":"supersecret123"}'

curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" -d '{"email":"you@example.com","password":"supersecret123"}'
# -> {"access_token": "..."}

curl -X POST http://localhost:8000/api/v1/repos/analyze \
  -H "Content-Type: application/json" -H "Authorization: Bearer <token>" \
  -d '{"repo_url": "https://github.com/octocat/Hello-World"}'
# -> {"repo_id": "...", "job_id": "..."}

curl http://localhost:8000/api/v1/jobs/<job_id> -H "Authorization: Bearer <token>"
# poll until "status": "completed"

curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" -H "Authorization: Bearer <token>" \
  -d '{"repo_id": "<repo_id>", "query": "readme"}'
```

## Chat with a repo (sub-project 2A)

Once a repo has finished analyzing, you can open a conversation and ask
questions about it. This requires a real LLM API key (Anthropic, OpenAI, or
Gemini) — without one, the chat endpoint returns a clean SSE `error`
event rather than crashing, but won't produce real answers.

1. Add to `backend/.env`:
   ```
   LLM_PROVIDER=anthropic
   ANTHROPIC_API_KEY=sk-ant-...
   ```
   (or `LLM_PROVIDER=openai` with `OPENAI_API_KEY=...`, or `LLM_PROVIDER=gemini` with `GEMINI_API_KEY=...`)
2. Restart the API (and worker, if running) so the new env vars are picked up.
3. Browse the file tree: `curl http://localhost:8000/api/v1/repos/<repo_id>/files -H "Authorization: Bearer <token>"`
4. Start a conversation:
   ```bash
   curl -X POST http://localhost:8000/api/v1/repos/<repo_id>/conversations \
     -H "Content-Type: application/json" -H "Authorization: Bearer <token>" \
     -d '{"title": "First chat"}'
   # -> {"id": "<conversation_id>", ...}
   ```
5. Send a message and watch the streamed response (SSE — `curl -N` to disable buffering):
   ```bash
   curl -N -X POST http://localhost:8000/api/v1/conversations/<conversation_id>/messages \
     -H "Content-Type: application/json" -H "Authorization: Bearer <token>" \
     -d '{"content": "What does this repo do?"}'
   ```
   You should see `event: tool_call`, `event: tool_result`, a stream of
   `event: token`, and a final `event: done` — with the assistant citing
   real files and line numbers from the repo.

This manual walkthrough is the only place this sub-project talks to a
real LLM API — all automated tests use a deterministic fake client (see
`docs/superpowers/specs/2026-08-16-agent-engine-design.md`).

## Non-goals in this phase

No LangGraph multi-agent workflow, no org/RBAC beyond one-workspace-per-user,
no load testing at scale, no Kubernetes deployment. (The frontend originally
scoped out here shipped in sub-project 2B below.)
See `docs/superpowers/specs/2026-08-16-analysis-core-design.md` for the full
design and the list of future sub-projects.

## Frontend (sub-project 2B)

A Next.js 14 IDE-style UI: browse an analyzed repo's file tree, view
syntax-highlighted source, and chat with the AI agent — all with
real-time streaming, dark/glassmorphism styling, and Framer Motion
micro-interactions.

### Local development

```bash
cd frontend
npm install
npm run dev
```
Requires the backend running (`docker compose up -d postgres redis`,
then `uvicorn app.main:app --reload` from `backend/`) at
`http://localhost:8000` (the default `BACKEND_URL`).

### Testing

- Component tests: `npm test` (from `frontend/`)
- End-to-end (Playwright): requires the full stack running with
  `LLM_PROVIDER=fake` (no real API key needed — see below) so the chat
  step gets a deterministic scripted reply. `npx playwright test`
  (from `frontend/`, after `npx playwright install --with-deps
  chromium` once). No live GitHub calls either: a `globalSetup`
  (`tests/e2e/global-setup.ts`) spins up a local git server serving
  the same fixture repo sub-project 1's worker tests use
  (`backend/tests/fixtures/sample_repo`) over dumb HTTP, and the suite
  submits that URL instead of a real GitHub URL. If the backend under
  test is running in a container that can't reach the host machine as
  `127.0.0.1` (e.g. the `worker` service in `docker compose`), set
  `E2E_FIXTURE_REPO_HOST=host.docker.internal` before running
  `playwright test`.

### Fake LLM provider mode

Set `LLM_PROVIDER=fake` (no API key required) to get a scripted chat
response instead of a real model — useful for local development and
the e2e suite without spending on a real API. Never use this in a
real deployment; it's a testing/dev convenience only.

### Guest access, no registration required (sub-project 3B)

The frontend no longer has registration or login pages. Visiting the app at
`/` lands you straight in the repo workspace at `/repos`: middleware calls
the backend's `POST /api/v1/auth/guest` transparently on first visit,
provisioning a temporary access token and setting a session cookie — there's
no account to create and no sign-in step. Each browser (or each fresh
incognito/private window) gets its own independent guest session this way.

**Everything on this deployment is public by design.** There is no private
data model: any repo URL submitted, the resulting analyzed file contents, job
error messages, and every conversation held about a repo (not just the
current visitor's own) are all readable by anyone who has the link — not
only the person who submitted or wrote them.

#### Optional: GitHub Star/Fork link

Set `NEXT_PUBLIC_GITHUB_REPO_URL` (a frontend build-time env var) to the
project's GitHub URL to show a "Star" link with a GitHub icon in the header.
It's unset by default, which hides the link entirely — no placeholder or
guessed URL is ever shown.

### Full stack via Docker

```bash
docker compose up -d --build
```
Brings up Postgres, Redis, the API, the worker, and the frontend
together. Visit `http://localhost:3000`. Copy `.env.example` to
`.env` at the repo root first if you want real chat responses
(`LLM_PROVIDER=anthropic`, `openai`, or `gemini` plus the matching API key) —
without it, chat gracefully shows a "not configured" message rather
than failing.

## Cloud deployment (Render + Vercel)

Runs the backend on Render and the frontend on Vercel, independently of any
local machine, on a 100%-free stack: `render.yaml` provisions a single free
Render web service, and Postgres/Redis come from external always-free
providers (Render's own free Postgres is deleted after 30 days, which isn't
"permanent"). The tradeoffs of going fully free are real and documented in
`render.yaml`'s and `backend/scripts/start_unified.sh`'s own comments —
worth a read before you commit to this path for something beyond a demo.

**1. Datastores (external, both genuinely free with no expiration)**
- Postgres — [neon.tech](https://neon.tech) or [supabase.com](https://supabase.com):
  create a project, then enable pgvector via their SQL editor:
  `CREATE EXTENSION IF NOT EXISTS vector;` (needed before the first
  deploy's Alembic migration runs). Copy the connection string they give
  you as-is — `Settings.database_url` upgrades a plain `postgresql://` to
  `postgresql+asyncpg://` automatically, and `db/session.py` strips the
  `sslmode`/`channel_binding` params these providers include by default.
- Redis — [upstash.com](https://upstash.com): create a Redis database,
  copy its `rediss://` connection string as-is (the extra "s" means
  TLS — both `arq` and `redis-py`, this app's two Redis clients,
  recognize that scheme natively, no extra config needed).

**2. Backend on Render**
- In the Render dashboard: New -> Blueprint -> point it at this GitHub repo.
  It provisions one free web service, `repo-analyzer`, running
  `backend/scripts/start_unified.sh` — both the FastAPI API and the ARQ
  background worker in the same container, since Render has no free tier
  for standalone worker services. This one step (connect + apply) can't be
  done from the Render CLI — Blueprint provisioning is Dashboard/API-only,
  the CLI only validates a render.yaml, it doesn't apply one.
- Generate a JWT keypair locally: `python backend/scripts/generate_keys.py`
  writes `backend/keys/jwt_private.pem` and `jwt_public.pem`. Set their
  contents directly as the `JWT_PRIVATE_KEY`/`JWT_PUBLIC_KEY` env vars
  (raw PEM text or base64 of it both work — see
  `app/core/security.py`'s `_load_pem`) rather than uploading Secret
  Files — plain env vars so the whole setup stays scriptable via the
  Render API/CLI instead of needing a dashboard file-upload step.
- Fill in the env vars the blueprint marks as secret (prompted automatically
  when you apply it): `DATABASE_URL` and `REDIS_URL` from step 1,
  `GROQ_API_KEY` at minimum, and the JWT keys above. `ANTHROPIC_API_KEY` /
  `OPENAI_API_KEY` / `GEMINI_API_KEY` are optional alternates —
  `get_llm_client()` falls back to whichever has a usable key.
- Once deployed, confirm `https://<your-service>.onrender.com/health`
  returns `{"status": "ok"}` — this is also the path Render's own uptime
  monitor polls (`healthCheckPath` in `render.yaml`).
- Startup note: the free plan spins down after 15min idle (~1min cold
  start on the next request).
- Feature note: `render.yaml` sets `ENABLE_EMBEDDING=false` on this
  deployment — confirmed live that loading the real ~500MB CodeBERT model
  during analysis's embedding step exceeds the free plan's 512MB even with
  `RUN_WORKER_IN_PROCESS`/`WARM_EMBEDDING_MODEL_ON_STARTUP` both already
  minimizing memory. Everything else works fully (repo analysis completes,
  chat answers using `list_directory`/`read_file`) — only vector similarity
  search (`search_code`) is unavailable on this specific deployment. Flip
  it back to `true` on a plan with enough RAM.

**3. Frontend on Vercel**
- Vercel dashboard: New Project -> import this GitHub repo -> set the root
  directory to `frontend/`. Vercel auto-detects Next.js; no build command
  changes needed.
- Set one env var: `BACKEND_URL` = your Render service's public URL (e.g.
  `https://repo-analyzer.onrender.com`, no trailing slash). This is a
  **server-only** var (deliberately not `NEXT_PUBLIC_*`) — every backend
  call is proxied through this Next.js app's own `app/api/**/route.ts`
  handlers (see `frontend/lib/backend.ts`), so the browser never talks to
  the Render API directly and no publicly-exposed API URL is needed.
- Deploy. The chat SSE and annotation routes set
  `export const maxDuration = 60` for Vercel's serverless function limit —
  raise it if you're on a Pro/Enterprise plan and see long turns time out.

**4. Wire them together**
- `CORS_ALLOWED_ORIGINS` on the Render API can stay empty — the proxy
  pattern above means the browser never calls the API's own origin, so no
  CORS headers are needed. Only set it (to your Vercel URL, or `*`) if you
  add something that calls the API straight from a browser.
- Optional: point a custom domain at the Vercel project and update
  `NEXT_PUBLIC_GITHUB_REPO_URL` (see above) if you want the header's GitHub
  link to match.

Both services redeploy automatically on every push to `master`.

## Known limitations

Under the current `--workers 4` uvicorn configuration, the first request that triggers the CodeBERT model's cold load can cause a several-minute worker instability window: each of the four uvicorn worker processes independently loads the ~500MB model into memory via a process-local cache, resulting in resource contention and temporary service degradation. Recommended mitigations for production: bake the model into the Docker image at build time, warm the model in FastAPI's startup lifespan before accepting traffic, or reduce the number of workers on the embedding-serving path.
