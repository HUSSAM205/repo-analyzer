#!/bin/bash
# Free-tier entrypoint: runs the API alone. The ARQ worker loop runs
# *inside* this same process instead of as a second OS process -- see
# app/main.py's lifespan and Settings.run_worker_in_process. Confirmed
# live that running them as two separate processes in one container (an
# earlier version of this script) still OOM'd a 512MB Render instance even
# with eager model warm-up disabled: each process imports its own copy of
# torch/transformers/langchain/langgraph regardless of whether it loads
# the actual model weights, and that import cost alone was too much
# doubled up. One process, one import of each library, is what actually
# fits. Requires RUN_WORKER_IN_PROCESS=true (and normally
# WARM_EMBEDDING_MODEL_ON_STARTUP=false) to be set alongside this script.
#
# Prefer separate api+worker services (docker-compose.yml, or a paid
# Render worker) whenever that's an option -- this trades away real CPU/
# memory isolation between request handling and background job execution,
# purely to fit a free tier's memory ceiling.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
