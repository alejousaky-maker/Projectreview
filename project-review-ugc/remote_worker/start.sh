#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${UGC_REMOTE_API_KEY:?Set UGC_REMOTE_API_KEY before starting the worker}"
exec .venv/bin/uvicorn remote_worker.worker:app --host 0.0.0.0 --port 8091 --workers 1
