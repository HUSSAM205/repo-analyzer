# Repo Analyzer — Analysis Core

Backend engine for the Autonomous AI GitHub Repository Deep Analyzer: clone a
repo, parse it with Tree-sitter, chunk it at function/class granularity,
embed chunks locally with CodeBERT, and search it via hybrid (vector +
keyword) search. No frontend in this phase — verified via API and tests.

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

## Non-goals in this phase

No frontend, no LangGraph multi-agent workflow, no org/RBAC beyond
one-workspace-per-user, no load testing at scale, no Kubernetes deployment.
See `docs/superpowers/specs/2026-08-16-analysis-core-design.md` for the full
design and the list of future sub-projects.

## Known limitations

Under the current `--workers 4` uvicorn configuration, the first request that triggers the CodeBERT model's cold load can cause a several-minute worker instability window: each of the four uvicorn worker processes independently loads the ~500MB model into memory via a process-local cache, resulting in resource contention and temporary service degradation. Recommended mitigations for production: bake the model into the Docker image at build time, warm the model in FastAPI's startup lifespan before accepting traffic, or reduce the number of workers on the embedding-serving path.
