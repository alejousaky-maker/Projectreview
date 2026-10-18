#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
echo '[worker] Preparing lightweight worker runtime (no model downloads)'
if [[ -x .venv/bin/python ]] && .venv/bin/python -c 'import sys; assert sys.version_info >= (3,11)' >/dev/null 2>&1; then
  worker_python="$PWD/.venv/bin/python"
else
  worker_python="$(command -v python3 || true)"
fi
[[ -n "$worker_python" ]] || { echo '[worker] ERROR: Python 3.11+ is required' >&2; exit 1; }
"$worker_python" -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
# A lightweight venv can coexist with the template's CUDA Python.
if [[ -z "${UGC_ML_ENV_PYTHON:-}" ]] && python3 -c 'import torch' >/dev/null 2>&1; then
  export UGC_ML_ENV_PYTHON="$(command -v python3)"
fi
export PYTHONPATH="$PWD/.worker-deps:$PWD${PYTHONPATH:+:$PYTHONPATH}"
if ! "$worker_python" - <<'CHECK'
from importlib.metadata import version
for line in open('requirements.txt'):
    if '==' in line:
        name,expected=line.strip().split('==')
        assert version(name)==expected
import fastapi, uvicorn, httpx, dotenv
CHECK
then
  echo '[worker] Installing required lightweight dependencies into persistent .worker-deps'
  worker_install_dir="$(mktemp -d /tmp/project-review-worker-deps.XXXXXX)"
  trap 'rm -rf "$worker_install_dir"' EXIT
  "$worker_python" -m pip install --disable-pip-version-check --target "$worker_install_dir/packages" -r requirements.txt
  "$worker_python" - "$worker_install_dir/packages" "$PWD/.worker-deps" <<'COPY'
import pathlib,shutil,sys,uuid
source=pathlib.Path(sys.argv[1]);target=pathlib.Path(sys.argv[2])
pending=target.with_name(target.name+'.pending-'+uuid.uuid4().hex)
# copyfile deliberately avoids chmod/copystat on restricted network volumes.
pending.mkdir()
for entry in source.rglob('*'):
    relative=entry.relative_to(source)
    if 'bin' in relative.parts or '__pycache__' in relative.parts:continue
    destination=pending/relative
    if entry.is_dir():destination.mkdir(exist_ok=True)
    elif entry.is_file():
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(entry,destination)
if target.exists():shutil.rmtree(target)
pending.rename(target)
COPY
  rm -rf "$worker_install_dir"
  trap - EXIT
fi
"$worker_python" - <<'CHECK'
import os,socket
import config
key=os.getenv('UGC_REMOTE_API_KEY','')
if not key.strip():raise SystemExit('[worker] ERROR: Set a nonempty UGC_REMOTE_API_KEY in RunPod environment variables')
try:
    with socket.socket() as sock:sock.bind(('0.0.0.0',8091))
except OSError:raise SystemExit('[worker] ERROR: Port 8091 is already occupied or unavailable; stop the previous worker and restart the Pod')
CHECK
echo '[worker] Starting authenticated worker on HTTP port 8091'
exec "$worker_python" -m uvicorn remote_worker.worker:app --host 0.0.0.0 --port 8091 --workers 1
