#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" == Darwin ]] && ! xcode-select -p >/dev/null 2>&1; then
  printf 'Install Apple Command Line Tools with:\nxcode-select --install\nThen run ./setup.sh again.\n'; exit 1
fi
command -v git >/dev/null || { echo 'Install git and run setup again.'; exit 1; }
command -v python3 >/dev/null || { echo 'Install Python 3.11 or newer and run setup again.'; exit 1; }
python3 -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
if [[ ! -f vendor/ugc-factory-core/examples/run_persona_example.py ]]; then
 git clone https://github.com/sipratt-p/ugc-factory-core.git vendor/ugc-factory-core
 git -C vendor/ugc-factory-core checkout --detach "$(cat scripts/upstream-revision.txt)"
fi
if [[ "${1:-}" == --gpu ]]; then
 python3 -m venv .gpu-venv
 .gpu-venv/bin/python -m pip install -r vendor/ugc-factory-core/requirements.txt
 echo 'GPU packages installed separately. Configure UGC_ML_ENV_PYTHON to .gpu-venv/bin/python; install ID-LoRA and scorer repositories and weights separately.'
else
 echo 'Controller installed. CUDA upstream dependencies are optional here; use ./setup.sh --gpu on your NVIDIA worker.'
fi
command -v ffmpeg >/dev/null || echo 'FFmpeg missing. On Mac install Homebrew, then: brew install ffmpeg'
.venv/bin/python doctor.py
printf 'No model weights were downloaded. Start with: .venv/bin/uvicorn app:app --host 0.0.0.0 --port 8090\n'
