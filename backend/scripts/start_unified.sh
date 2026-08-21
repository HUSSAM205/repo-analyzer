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

PORT="${PORT:-8000}"

# --workers 1, not the Dockerfile default of 4 -- each uvicorn worker
# process loads its own separate copy of the ~500MB CodeBERT model (see
# README's "Known limitations"), and a free-tier instance's memory can't
# absorb four of those on top of the arq worker's own copy.
uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers 1 &
API_PID=$!

# Wait for the API to actually bind its port and respond before starting
# the worker. Confirmed live: starting both processes at once (even with
# WARM_EMBEDDING_MODEL_ON_STARTUP=false, so neither loads the CodeBERT
# model eagerly) still means both import torch/transformers/langchain/
# langgraph at the same moment -- on a free-tier instance's throttled CPU
# share, that contention was slow enough that uvicorn never bound its port
# within Render's scan window ("Port scan timeout reached, no open ports
# detected", not an OOM -- the earlier memory fix held, this is a separate,
# sequencing problem). Starting the worker only after the API is confirmed
# listening means it isn't competing for CPU during the one window the
# platform's port scan actually watches.
READY=0
for _ in $(seq 1 90); do
    if curl -sf "http://127.0.0.1:${PORT}/health" > /dev/null 2>&1; then
        READY=1
        break
    fi
    sleep 2
done

if [ "$READY" -ne 1 ]; then
    echo "start_unified.sh: API did not become ready within the wait budget" >&2
    kill -TERM "$API_PID" 2>/dev/null || true
    exit 1
fi

arq app.workers.settings.WorkerSettings &
WORKER_PID=$!

# Fail fast: if either process dies, exit so the platform restarts the
# whole container, rather than silently keep running in a half-broken
# state (HTTP serving fine but no analysis jobs ever running, or vice
# versa).
trap 'kill -TERM $WORKER_PID $API_PID 2>/dev/null || true' TERM INT

wait -n "$WORKER_PID" "$API_PID"
EXIT_CODE=$?
kill -TERM "$WORKER_PID" "$API_PID" 2>/dev/null || true
exit "$EXIT_CODE"
