#!/bin/bash
# Runs the ARQ background worker and the FastAPI server in a single
# container -- for free-tier hosting where a separate paid worker service
# isn't an option (Render, for example, has no free tier for Background
# Workers at all). This trades away the CPU isolation the two-container
# setup (docker-compose.yml's separate api/worker services) was built for
# -- see Settings.embedding_cpu_threads' docstring -- a heavy embedding job
# running in this same container can slow HTTP responses during that job.
# Prefer separate api+worker services whenever a paid worker plan is an
# option; this script exists for the 100%-free path specifically.
set -uo pipefail

arq app.workers.settings.WorkerSettings &
WORKER_PID=$!

# --workers 1, not the Dockerfile default of 4 -- each uvicorn worker
# process loads its own separate copy of the ~500MB CodeBERT model (see
# README's "Known limitations"), and a free-tier instance's memory can't
# absorb four of those on top of the arq worker's own copy.
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 &
API_PID=$!

# Fail fast: if either process dies, exit so the platform restarts the
# whole container, rather than silently keep running in a half-broken
# state (HTTP serving fine but no analysis jobs ever running, or vice
# versa).
trap 'kill -TERM $WORKER_PID $API_PID 2>/dev/null || true' TERM INT

wait -n "$WORKER_PID" "$API_PID"
EXIT_CODE=$?
kill -TERM "$WORKER_PID" "$API_PID" 2>/dev/null || true
exit "$EXIT_CODE"
